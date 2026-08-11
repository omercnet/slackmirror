FROM python:3.12-alpine@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df

ENV PORT 3000

WORKDIR /usr/src/app

# Create app directory
WORKDIR /usr/src/app/

COPY Pipfile .
COPY Pipfile.lock .

# Install reqs
RUN pip install pipenv
RUN apk add build-base && \
	pipenv lock -r > requirements.txt && \
	pip install -r requirements.txt && \
	apk del build-base

COPY . .

USER 1000

CMD [ "python", "/usr/src/app/app.py" ]