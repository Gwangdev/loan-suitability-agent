# 공식 Caddy 이미지는 root로 뜨고, 인증서를 두는 /data와 설정을 자동 저장하는 /config도 root
# 소유다. compose에서 사용자만 바꾸면 새로 만든 이름 있는 볼륨이 이미지 경로의 root 소유권을
# 물려받아 Caddy가 인증서를 쓰지 못한다. 두 경로를 앱 컨테이너와 같은 uid 소유로 만든 뒤 그
# 사용자로 전환한다. 80·443 바인딩은 바이너리에 붙은 cap_net_bind_service가 맡으므로 root가
# 필요 없다.
FROM caddy:2-alpine
RUN mkdir -p /data /config && chown -R 10001:10001 /data /config
USER 10001:10001
