#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from enum import Enum
from decimal import *
from collections import defaultdict, namedtuple
import time

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.select import Select
from texttable import Texttable

from .question import Question
from ...data.exceptions import *
from tiltr.driver.utils import set_element_value


ClozeScoring = namedtuple('ClozeScoring', ['identical_scoring', 'comparator', 'gaps'])

TextualGapScoring = namedtuple(
	'TextualGapScoring', ['cloze_type', 'size', 'options'])
NumericGapScoring = namedtuple(
	'NumericGapScoring', ['cloze_type', 'value', 'lower', 'upper', 'score'])


def _create_gaps(scoring):
	constructors = dict((
		(ClozeType.text, ClozeQuestionTextGap),
		(ClozeType.select, ClozeQuestionSelectGap),
		(ClozeType.numeric, ClozeQuestionNumericGap)))

	gaps = dict()
	for gap_index, gap_scoring in enumerate(scoring.gaps):
		construct_gap = constructors[gap_scoring.cloze_type]
		gap = construct_gap(scoring, gap_index)
		gaps[gap_index] = gap

	return gaps


def _max_entry_size(size, context):
	# get the maximum number of characters we write into this gap. note that
	# this might be != the real maximum size, which might be unlimited, so we
	# choose some configured maximum number for entry purposes.
	if size is not None:
		return size
	else:
		return int(context.settings.max_cloze_text_length)


def _modify_answer(text, context, max_len=None):
	max_len = _max_entry_size(max_len, context)

	mode = context.random.choices(
		("unmodified", "randchar", "randcase", "randperm", "randfull"),
		weights=(0.5, 0.2, 0.1, 0.1, 0.1))[0]

	if mode == "unmodified":
		# keep exactly as specified.
		return text
	elif mode == "randperm":
		text = ''.join(context.random.sample(text, len(text)))
		return text
	elif mode == "randfull":
		return context.produce_text(max_len, context.cloze_random_chars)
	else:
		# modify case or content.
		chars = []
		for i in range(len(text)):
			r = context.random.random()
			if mode == "randchar" and r < 0.2:
				chars.append(context.random.choice(context.cloze_random_chars))
			elif mode == "randcase" and r < 0.2:
				chars.append(text[i].swapcase())
			else:
				chars.append(text[i])
		text = "".join(chars)
		return text


def _readjust_score(random, score, boost):
	if random.randint(1, 10) == 5:
		return Decimal(0)
	else:
		return Decimal(random.randint(1, 3 * 4)) / Decimal(4)


def _readjust(context, scoring, gap, actual_answers):
	# FIXME: rejection of entry of zero points should be checked via UI

	random = context.random

	if scoring.cloze_type == ClozeType.numeric:
		new_score = Decimal(0)
		i = 0

		while new_score <= Decimal(0):
			new_score = _readjust_score(random, scoring.score, i)
			i += 1

		return scoring._replace(
			score=new_score)

	else:  # text and select gaps

		# FIXME remove options here. currently not possible due to
		# https://mantis.ilias.de/view.php?id=25238

		unscored_answers = set(actual_answers) - set(gap.get_scored_options().keys())

		new_options = dict()
		for k, v in scoring.options.items():
			new_options[k] = v

		# add new answers
		for _ in range(random.randint(0, min(max(2, len(unscored_answers)), 10))):
			while True:
				if scoring.cloze_type == ClozeType.text and len(unscored_answers) > 0 and random.randint(1, 10) > 1:
					new_answer = context.random.choice(list(unscored_answers))
					unscored_answers.remove(new_answer)
				else:
					new_answer, ignored_score = gap.get_random_choice(context)

					if scoring.cloze_type == ClozeType.select:
						new_answer = _modify_answer(new_answer, context)

					new_answer = new_answer.strip()
					new_answer = new_answer.replace('\t', '')

				if len(new_answer) > 0 and new_answer not in new_options:
					new_options[new_answer] = Decimal(random.randint(1, 8)) / Decimal(4)
					break

		i = 0
		while True:
			readjusted_options = dict()

			for k, score in new_options.items():
				readjusted_options[k] = _readjust_score(random, score, i)

			if any(score > Decimal(0) for score in readjusted_options.values()):
				break

			i += 1

		return scoring._replace(options=readjusted_options)


class ClozeType(Enum):
	text = 0
	select = 1
	numeric = 2


class ClozeComparator(Enum):
	ignore_case = "ci"
	case_sensitive = "cs"


class ClozeQuestionGap:
	_export_names = dict(de="Lücke", en="Gap")

	def __init__(self, index):
		self.index = index

	def get_maximum_score(self):
		raise NotImplementedError()

	def get_export_name(self, language):
		return ClozeQuestionGap._export_names[language] + " " + str(self.index + 1)

	def is_valid_answer(self, value):
		raise NotImplementedError()


class ClozeQuestionTextGap(ClozeQuestionGap):
	def __init__(self, scoring, index):
		ClozeQuestionGap.__init__(self, index)
		self.comparator = scoring.comparator
		gap_scoring = scoring.gaps[index]
		self.options = gap_scoring.options
		self.size = gap_scoring.size  # maximum size

	def get_maximum_score(self):
		return max(self.options.values())

	def _get_maximum_entry_size(self, context):
		return _max_entry_size(self.size, context)

	def initialize_coverage(self, question, coverage, context):
		size = self._get_maximum_entry_size(context)
		for mode in ("verify", "export"):
			for args in coverage.text_cases(size, context):
				coverage.add_case(question, self.index, mode, *args)
			for solution in self.options.keys():
				coverage.add_case(question, self.index, mode, "solution", solution)

	def add_coverage(self, question, channel, coverage, value):
		value = str(value)
		for args in coverage.text_cases_occurred(value):
			coverage.case_occurred(question, self.index, channel, *args)
		if value in self.options:
			coverage.case_occurred(question, self.index, channel, "solution", value)

	def _modify_answer(self, text, context):
		text = _modify_answer(text, context, self.size)
		return text, self.get_score(text)

	def get_random_choice(self, context):
		if context.random.random() < float(context.settings.cloze_text_enter_scored_p) and not context.prefer_text():
			# pick scored answer.
			text, _ = context.random.choice(list(self.options.items()))
			return self._modify_answer(text, context)
		else:
			# make up something random and probably wrong.
			if context.random.random() < float(context.settings.cloze_text_enter_random_number_p):
				# insert a random number. this is useful to test
				# workarounds.implicit_text_number_conversions.
				num_digits = context.random.randint(0, 2)
				format = (".%d" % num_digits) + "%f"
				text = format % (context.random.random() * 1000)
			else:
				# produce some random test.
				entry_size = self._get_maximum_entry_size(context)
				text = context.produce_text(
					entry_size, context.cloze_random_chars)
			return text, self.get_score(text)

	def get_score(self, text):
		if self.comparator == ClozeComparator.case_sensitive:
			return self.options.get(text, Decimal(0))

		assert self.comparator == ClozeComparator.ignore_case
		best_score = Decimal(0)
		for option, score in self.options.items():
			if option.casefold() == text.casefold():
				best_score = max(best_score, score)

		return best_score

	def get_scored_options(self):
		return self.options

	def is_valid_answer(self, value):
		if self.size is None:  # no restriction?
			return True
		else:
			return len(value) <= self.size

	def get_type(self):
		return ClozeType.text


class ClozeQuestionSelectGap(ClozeQuestionGap):
	def __init__(self, scoring, index):
		ClozeQuestionGap.__init__(self, index)
		self.options = scoring.gaps[index].options

	def get_maximum_score(self):
		return max(self.options.values())

	def initialize_coverage(self, question, coverage, context):
		for value in self.options.keys():
			for mode in ("verify", "export"):
				coverage.add_case(question, self.index, mode, value)

	def add_coverage(self, question, channel, coverage, value):
		value = str(value)
		coverage.case_occurred(question, self.index, channel, value)

	def get_random_choice(self, context):
		return context.random.choice(list(self.options.items()))

	def get_score(self, text):
		return self.options.get(text, Decimal(0))

	def get_scored_options(self):
		return self.options

	def is_valid_answer(self, value):
		return value in self.options

	def get_type(self):
		return ClozeType.select


class ClozeQuestionNumericGap(ClozeQuestionGap):
	def __init__(self, scoring, index):
		ClozeQuestionGap.__init__(self, index)

		gap_scoring = scoring.gaps[index]

		self.numeric_value = gap_scoring.value
		self.numeric_lower = gap_scoring.lower
		self.numeric_upper = gap_scoring.upper
		self.score = gap_scoring.score

		# ILIAS will limit exports to XLS to 16 significant decimals, which makes sense.
		# e.g. 25.433019319138662 -> 25.43301931913866, 0.17493771424585164 -> 0.1749377142458516
		self.format = '%.16g'

	def get_maximum_score(self):
		return self.score

	def initialize_coverage(self, question, coverage, context):
		for mode in ("verify", "export"):
			coverage.add_case(question, self.index, mode, str(self.numeric_value))
			coverage.add_case(question, self.index, mode, str(self.numeric_lower))
			coverage.add_case(question, self.index, mode, str(self.numeric_upper))

	def add_coverage(self, question, channel, coverage, value):
		x = str(value)
		if x in [str(self.numeric_value), str(self.numeric_lower), str(self.numeric_upper)]:
			coverage.case_occurred(question, self.index, channel, x)

	def _get_random_inside(self, context):
		return context.random.uniform(float(self.numeric_lower), float(self.numeric_upper))

	def _get_random_outside(self, context):
		r = 14  # generate fake numbers up to this scale
		d = float(self.numeric_upper - self.numeric_lower)
		off = context.random.uniform(10 ** -r, (10 ** r) * d)

		return context.random.choice((
			float(self.numeric_lower) - off,
			float(self.numeric_upper) + off
		))

	def get_random_choice(self, context):
		s = None

		if not context.workarounds.disallow_invalid_answers:
			if context.random.random() < float(context.settings.invalid_answer_p):
				s = context.produce_text(20, context.cloze_random_chars, allow_numbers=False)

		if s is None:
			g = context.random.choice((
				lambda _: float(self.numeric_lower),
				lambda _: float(self.numeric_upper),
				self._get_random_inside,
				self._get_random_outside
			))

			n = g(context)
			s = self.format % n

		return s, self.get_score(s)

	def get_score(self, text):
		try:
			n = float(text)
			n = float(self.format % n)  # limit to number of representable digits

			if float(self.numeric_lower) <= n <= float(self.numeric_upper):
				return self.score
			else:
				return Decimal(0)
		except ValueError:
			return Decimal(0)

	def get_scored_options(self):
		return dict((self.numeric_value, self.score))

	def is_valid_answer(self, value):
		value = value.strip()
		if len(value) == 0:
			return True
		try:
			float(value)
			return True
		except ValueError:
			return False

	def get_type(self):
		return ClozeType.numeric


def parse_gap_size(driver, gap_index):
	element = driver.find_element_by_name("gap_%d_gapsize" % gap_index)
	text = element.get_attribute("value").strip()
	assert isinstance(text, str)
	if text == '':
		return None
	else:
		return int(text)


def parse_numeric_gap_scoring(driver, gap_index):
	value = Decimal(driver.find_element_by_name("gap_%d_numeric" % gap_index).get_attribute("value"))
	lower = Decimal(driver.find_element_by_name("gap_%d_numeric_lower" % gap_index).get_attribute("value"))
	upper = Decimal(driver.find_element_by_name("gap_%d_numeric_upper" % gap_index).get_attribute("value"))
	score = Decimal(driver.find_element_by_name("gap_%d_numeric_points" % gap_index).get_attribute("value"))
	return dict(value=value, lower=lower, upper=upper, score=score)


def update_numeric_gap_scoring(driver, gap_index, gap):
	set_element_value(driver, driver.find_element_by_name("gap_%d_numeric_points" % gap_index), str(gap.score))


def parse_gap_options(driver, gap_index):
	options = dict()
	seen = set()

	while True:
		try:
			answer = driver.find_element_by_id("gap_%d[answer][%d]" % (gap_index, len(options)))
		except NoSuchElementException:
			break
		points = driver.find_element_by_id("gap_%d[points][%d]" % (gap_index, len(options)))

		answer_key = answer.get_attribute("value")

		if answer_key.strip() in seen:
			raise InteractionException("the gap has multiple identical options named '%s'. unsupported." % answer_key)
		seen.add(answer_key.strip())

		options[answer_key] = Decimal(points.get_attribute("value"))

	return options


def update_gap_options(driver, gap_index, options):
	old_keys = set()
	new_keys = set(options.keys())

	# for some obscure reason, setting answers and scores via set_element_value() won't
	# work here. send_keys() works though.

	def get_option_answer_element(option_index):
		return driver.find_element_by_id("gap_%d[answer][%d]" % (gap_index, option_index))

	def get_option_answer(option_index):
		return get_option_answer_element(option_index).get_attribute("value")

	option_index = 0
	while True:
		try:
			option_key = get_option_answer(option_index)
		except NoSuchElementException:
			break

		old_keys.add(option_key)

		option_index += 1

	# add options.
	for option_key in new_keys - old_keys:
		driver.find_element_by_name("add_gap_%d_%d" % (gap_index, option_index - 1)).click()

		element = get_option_answer_element(option_index)
		element.send_keys(option_key)
		#set_element_value(driver, element, option_key)

		if element.get_attribute("value") != option_key:
			print("gap option name mismatch: '%s' != '%s'" % (element.get_attribute("value"), option_key))
			raise InteractionException("failed to set gap option name")

		# debug
		#for i in range(option_index):
		#	answer = get_option_answer(i)
		#	print("debug option %d %s" % (i, answer))

		option_index += 1

	# remove options.
	option_index = 0
	while True:
		try:
			option_key = get_option_answer(option_index)
		except NoSuchElementException:
			break

		if len(option_key.strip()) == 0:
			raise InteractionException("illegal empty option name")

		if option_key not in new_keys:
			driver.find_element_by_name("remove_gap_%d_%d" % (gap_index, option_index)).click()
		else:
			option_index += 1

	option_count = option_index

	# set all scores.
	for option_index in range(option_count):
		option_key = get_option_answer(option_index)

		points = driver.find_element_by_id("gap_%d[points][%d]" % (gap_index, option_index))
		points.clear()
		points.send_keys(str(options[option_key]))


class ClozeQuestion(Question):
	@staticmethod
	def _get_ui(driver):
		fixed_text_length = driver.find_element_by_name("fixedTextLength").get_attribute("value").strip()
		if fixed_text_length == '':
			fixed_text_length = None
		else:
			fixed_text_length = int(fixed_text_length)

		gaps = list()

		while True:
			gap_index = len(gaps)

			try:
				cloze_type_element = driver.find_element_by_name("clozetype_%d" % gap_index)
			except NoSuchElementException:
				break

			cloze_type = ClozeType(int(cloze_type_element.get_attribute("value")))

			if cloze_type != ClozeType.select:
				gap_size = parse_gap_size(driver, gap_index)
				if gap_size is None:
					gap_size = fixed_text_length
			else:
				gap_size = None

			if cloze_type in (ClozeType.text, ClozeType.select):
				options = parse_gap_options(driver, gap_index)

				if not options:
					raise InteractionException("did not find gap options (%d)" % gap_index)

				scoring = TextualGapScoring(
					cloze_type=cloze_type, size=gap_size, options=options)

			elif cloze_type == ClozeType.numeric:
				scoring = NumericGapScoring(
					cloze_type=ClozeType.numeric,
					**parse_numeric_gap_scoring(driver, gap_index))

			else:
				raise NotImplementedException("unsupported cloze type " + str(cloze_type))

			gaps.append(scoring)

		identical_scoring = driver.find_element_by_name("identical_scoring").is_selected()

		comparator = ClozeComparator(driver.find_element_by_css_selector(
			"#textgap_rating option[selected]").get_attribute("value"))

		return ClozeScoring(
			identical_scoring=identical_scoring,
			comparator=comparator,
			gaps=gaps)

	@staticmethod
	def _set_ui(driver, scoring):
		identical_scoring_checkbox = driver.find_element_by_name("identical_scoring")
		if identical_scoring_checkbox.is_selected() != scoring.identical_scoring:
			identical_scoring_checkbox.click()

		Select(driver.find_element_by_id("textgap_rating")).select_by_value(
			scoring.comparator.value)

		for gap_index, gap in enumerate(scoring.gaps):
			n_tries = 0
			while True:
				try:
					if gap.cloze_type in (ClozeType.text, ClozeType.select):
						update_gap_options(driver, gap_index, gap.options)
					else:
						update_numeric_gap_scoring(driver, gap_index, gap)
					break
				except NoSuchElementException:
					n_tries += 1
					if n_tries > 5:
						raise

	def _create_gaps(self):
		self.gaps = _create_gaps(self.scoring)

	def __init__(self, driver, title, settings):
		super().__init__(title)

		self.scoring = self._get_ui(driver)
		self._create_gaps()

	def get_maximum_score(self, context):
		return sum([gap.get_maximum_score() for gap in self.gaps.values()])

	def create_answer(self, driver, *args):
		from ..answers.cloze import ClozeAnswer
		return ClozeAnswer(driver, self, *args)

	def initialize_coverage(self, coverage, context):
		for gap in self.gaps.values():
			gap.initialize_coverage(self, coverage, context)

	def add_export_coverage(self, coverage, answers, language):
		gaps = dict()
		for gap in self.gaps.values():
			gaps[gap.get_export_name(language)] = self.gaps[gap.index]
		for gap_name, value in answers.items():
			gaps[gap_name].add_coverage(self, "export", coverage, str(value))

	def get_gap_definition(self, index):
		return self.gap[index]

	def _get_normalized(self, s):
		if self.scoring.comparator == ClozeComparator.case_sensitive:
			return s
		else:
			assert self.scoring.comparator == ClozeComparator.ignore_case
			return s.casefold()

	def _is_empty_answer(self, answer, context):
		answer = context.strip_whitespace(answer)
		return len(answer) == 0

	def get_random_answer(self, context):
		while True:
			answers = dict()
			valid = dict()

			previous_answers = defaultdict(set)
			previous_answers_p = float(context.settings.cloze_previous_answer_p)
			all_empty = True

			shuffled_gaps = list(self.gaps.values())
			context.random.shuffle(shuffled_gaps)  # randomize our "previous" value logic

			for gap in shuffled_gaps:
				previous = previous_answers[gap.get_type()]
				choice = None

				if len(previous) > 0 and context.random.random() < previous_answers_p:
					# use some previous answer to explicitly test identical_scoring
					# option, though it's also tested through the case below.
					choice = context.random.choice(list(previous))

					# trying to set a select gap to some illegal value causes problems.
					if not gap.is_valid_answer(choice):
						choice = None

				if choice is None:
					choice, _ = gap.get_random_choice(context)

				previous.add(choice)

				answers[gap.index] = choice
				valid[gap.index] = gap.is_valid_answer(choice)
				all_empty = all_empty and self._is_empty_answer(choice, context)

			if all_empty and context.workarounds.disallow_empty_answers:
				pass  # retry
			else:
				return answers, valid, self.compute_score_by_indices(answers, context)

	def readjust_scores(self, driver, actual_answers, context, report):
		def random_flip(f):
			if context.random.randint(0, 3) == 0:  # flip?
				return not f
			else:
				return f

		def random_flip_comparator(c):
			if context.random.randint(0, 3) == 0:  # flip?
				return context.random.choice([x for x in list(ClozeComparator) if x != c])
			else:
				return c

		old_scoring = self.scoring

		self.scoring = ClozeScoring(
			identical_scoring=random_flip(self.scoring.identical_scoring),
			comparator=random_flip_comparator(self.scoring.comparator),
			gaps=[_readjust(context, s, self.gaps[i], actual_answers[self.gaps[i].get_export_name(context.language)])
				  for i, s in enumerate(self.scoring.gaps)])
		self._create_gaps()
		self._set_ui(driver, self.scoring)

		table = Texttable()
		table.set_deco(Texttable.HEADER)
		table.set_cols_dtype(['t', 'a', 'a'])
		table.add_row(['', 'old', 'readjusted'])

		table.add_row([
			'identical_scoring',
			old_scoring.identical_scoring,
			self.scoring.identical_scoring])

		table.add_row([
			'comparator',
			old_scoring.comparator.name,
			self.scoring.comparator.name])

		for i, (old_gap, new_gap) in enumerate(zip(old_scoring.gaps, self.scoring.gaps)):
			table.add_row(["", "", ""])
			table.add_row(["gap %d" % (1 + i), "", ""])

			assert old_gap.cloze_type == new_gap.cloze_type
			if old_gap.cloze_type == ClozeType.numeric:
				for key in ('value', 'lower', 'upper', 'score'):
					table.add_row([
						key,
						getattr(old_gap, key),
						getattr(new_gap, key)])
			else:
				table.add_row([
					'size',
					old_gap.size or "no limit",
					new_gap.size or "no limit"])

				for key in set(old_gap.options.keys()) | set(new_gap.options.keys()):
					table.add_row([
						key,
						old_gap.options.get(key, "n/a"),
						new_gap.options.get(key, "n/a")])

		report(table)

		return True, list()

	def compute_score(self, answers, context):
		name_to_index = dict()
		for gap in self.gaps.values():
			name_to_index[gap.get_export_name(context.language)] = gap.index

		indexed_answers = dict()
		for name, value in answers.items():
			indexed_answers[name_to_index[name]] = value

		return self.compute_score_by_indices(indexed_answers, context)

	def compute_score_by_indices(self, answers, context):
		score = Decimal(0)

		if self.scoring.identical_scoring:
			for index, text in answers.items():
				score += self.gaps[index].get_score(text)
		else:
			# make sure answers are sorted as self.identical_scoring won't be
			# computed correctly otherwise.
			sorted_answers = sorted(list(answers.items()), key=lambda x: int(x[0]))

			given_answers = set()
			for index, text in sorted_answers:
				comparable_text = text

				if not context.workarounds.identical_scoring_ignores_comparator:
					if self.scoring.comparator == ClozeComparator.ignore_case:
						comparable_text = text.casefold()
				if comparable_text in given_answers:
					continue
				given_answers.add(comparable_text)

				score += self.gaps[index].get_score(text)

		return score
