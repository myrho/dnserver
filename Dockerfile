FROM python:3.6-alpine

LABEL maintainer "s@muelcolvin.com"

RUN pip install dnslib==0.9.7

RUN mkdir /zones
ADD ./example_zones.txt /zones/zones.txt
ADD ./example_internal_zones.txt /zones/internal_zones.txt

ADD ./dnserver.py /home/root/dnserver.py
ADD ./dnslib /home/root/dnslib
EXPOSE 53/tcp
EXPOSE 53/udp
EXPOSE 5000
CMD ["/home/root/dnserver.py"]
