FROM python:3.12-alpine

# Outplane routes to 8080. The server reads $PORT if the platform sets one.
ENV PORT=8080 PYTHONUNBUFFERED=1
WORKDIR /app

COPY server.py /app/server.py
COPY public /app/public

RUN adduser -D web
USER web

EXPOSE 8080
CMD ["python", "/app/server.py"]
