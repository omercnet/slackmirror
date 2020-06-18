FROM python:3.8-alpine

ENV LISTEN_PORT 3000

WORKDIR /usr/src/app

# Create app directory
WORKDIR /usr/src/app/

COPY app/Pipfile .
COPY app/Pipfile.lock .

# Install reqs
RUN pip install pipenv
RUN apk add build-base && \
	pipenv lock -r > requirements.txt && \
	pip install -r requirements.txt && \
	apk del build-base

COPY app/ .

USER 1000

CMD [ "python", "/usr/src/app/app.py" ]