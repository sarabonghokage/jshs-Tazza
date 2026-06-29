FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 영구 데이터 위치(호스팅에서 볼륨을 /data 에 마운트하면 DB 가 보존된다)
ENV DATA_DIR=/data
# 대부분의 호스팅은 PORT 를 주입한다. 없으면 8080 사용.
ENV PORT=8080

EXPOSE 8080

CMD ["python", "app.py"]
