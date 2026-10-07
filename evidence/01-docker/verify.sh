#!/usr/bin/env bash
# PRE-02 step 3 — post-install verification in a FRESH SSH session, WITHOUT sudo
# (a new login is what applies the docker group membership).
# Run: ssh -p 9922 user@<VM> 'bash -s' < verify.sh
set -u
sec() { printf '\n===== %s =====\n' "$1"; }
run() { printf '$ %s\n' "$*"; "$@" 2>&1 || printf '(exit %s)\n' "$?"; }

sec "A. docker --version";        run docker --version
sec "B. docker compose version";  run docker compose version
run docker buildx version
sec "C. SERVICE STATUS"
run systemctl is-active docker containerd
run systemctl is-enabled docker containerd
sec "D. docker info (no sudo)"
run docker info --format 'ServerVersion={{.ServerVersion}} StorageDriver={{.Driver}} CgroupDriver={{.CgroupDriver}} CgroupVersion={{.CgroupVersion}} RootDir={{.DockerRootDir}} Containers={{.Containers}} Images={{.Images}}'
sec "E. GROUP MEMBERSHIP"
run id
run getent group docker
sec "F/G. DISPOSABLE TEST CONTAINER (no sudo, no ports, removed after run)"
run docker run --rm hello-world
run docker ps -a
run docker image rm hello-world
run docker images
sec "H. LISTENING PORTS"
run ss -tlnH
run docker network ls
run docker volume ls
sec "I. DISK"
run df -h /
run docker system df
sec "PACKAGE SOURCE"
run dpkg-query -W -f='${Package} ${Version}\n' docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras
run apt-cache policy docker-ce
