FROM ubuntu:latest
#FROM ubuntu:16.04
#FROM ubuntu:16.10
MAINTAINER Bernhard.Liebl@rz.uni-regensburg.de

# install essential dependencies.
# RUN apt-get update -y && apt-get install -y firefox wget iputils-ping vim npm curl unzip python3-pip \
#     && pip3 install selenium requests openpyxl tornado pytz humanize pdb-clone pillow pdfminer3 PyMySQL texttable numpy scipy \
#     && npm i -g bulma jquery open-iconic plotly.js bulma-accordion

RUN apt-get update -y && apt-get install -y firefox wget iputils-ping vim npm curl unzip
RUN apt-get update -y && apt-get install -y python3-pip python3-venv
RUN mkdir /root/venv \
    && python3 -m venv /root/venv \
    && /root/venv/bin/python3 -m pip install --no-cache-dir selenium requests openpyxl tornado pytz humanize pdb-clone pillow pdfminer3 PyMySQL texttable numpy scipy
RUN npm i -g bulma jquery open-iconic plotly.js bulma-accordion
