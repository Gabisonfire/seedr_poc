FROM python:3.10-alpine
COPY . .
RUN pip install pipenv && pipenv sync
CMD ["pipenv", "run", "python", "seedr.py"]