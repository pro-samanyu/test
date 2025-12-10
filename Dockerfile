# Dockerfile
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y tmate openssh-client curl git && rm -rf /var/lib/apt/lists/*
CMD ["/bin/bash"]

# Build
docker build -t ubuntu-22.04-with-tmate .
