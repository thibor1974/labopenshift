FROM registry.access.redhat.com/ubi8/ubi-minimal@sha256:e83a3146aa8d34dccfb99097aa79a3914327942337890aa6f73911996a80ebb8

LABEL description="a test from thib using apache"

RUN echo "Hello from Dockerfile" > /usr/share/httpd/noindex/index.html

expose 80

ENTRYPOINT ["httpd", "-D","FOREGROUND"]
