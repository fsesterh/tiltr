#FROM ubuntu:latest
#FROM ubuntu:16.04
#FROM ubuntu:16.10
FROM ubuntu:20.04
ARG DEBIAN_FRONTEND=noninteractive
MAINTAINER Bernhard.Liebl@rz.uni-regensburg.de

# install essential dependencies.
# RUN apt-get update -y && apt-get install -y firefox wget iputils-ping vim npm curl unzip python3-pip \
#     && pip3 install selenium requests openpyxl tornado pytz humanize pdb-clone pillow pdfminer3 PyMySQL texttable numpy scipy \
#     && npm i -g bulma jquery open-iconic plotly.js bulma-accordion

RUN apt-get update -y && apt-get install -y firefox wget iputils-ping vim npm curl unzip
RUN apt-get update -y && apt-get install -y python3-pip python3-venv
RUN mkdir /root/venv \
    && python3 -m venv /root/venv \
#    && /root/venv/bin/python3 -m pip install --no-cache-dir firefox iputils-ping vim curl
#RUN python3 -m venv /root/venv \
    && /root/venv/bin/python3 -m pip install --no-cache-dir selenium requests openpyxl tornado pytz humanize pdb-clone pillow pdfminer3 PyMySQL texttable numpy scipy pandora p 
#RUN python3 -m venv /root/venv \
#    && /root/venv/bin/python3 -m pip install --no-cache-dir curl
# firefox iputils-ping vim und curl fehlen  wegen inkompatibiltäten unter python3 stattessen in apt-get...
RUN npm i -g bulma jquery open-iconic plotly.js bulma-accordion


#RUN apt-get update -y && apt-get install -y firefox wget iputils-ping vim npm curl unzip python3-pip \
#    && pip3 install selenium requests openpyxl tornado pytz humanize pdb-clone pillow pdfminer3 PyMySQL texttable numpy scipy \
#    && npm i -g bulma jquery open-iconic plotly.js bulma-accordion
