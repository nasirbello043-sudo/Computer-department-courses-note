# Tools image for the Learning Hub generator: LaTeX, poppler and the Python libraries.
# Built once by the build-tools workflow, then reused by every generate run.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv git ca-certificates \
      texlive-latex-base texlive-latex-recommended texlive-latex-extra \
      texlive-fonts-recommended poppler-utils \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --break-system-packages reportlab matplotlib
RUN ln -sf /usr/bin/python3 /usr/local/bin/python
WORKDIR /work
