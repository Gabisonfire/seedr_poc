FROM python:3.9.9-alpine
COPY . .
RUN pip install pipenv && pipenv sync
CMD ["pipenv", "run", "python", "seedr.py"]