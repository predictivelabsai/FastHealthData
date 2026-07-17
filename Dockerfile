FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV FASTHEALTHDATA_DB=/data/fasthealthdata.sqlite
ENV FASTHEALTHDATA_PORT=5013
EXPOSE 5013
CMD ["sh", "-c", "python -c 'import db,seed; seed.build() if not db.db_exists() else None' && python web_app.py"]
