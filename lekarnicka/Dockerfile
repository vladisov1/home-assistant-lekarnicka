FROM python:3.12-alpine
WORKDIR /app
RUN pip install --no-cache-dir flask==3.1.1 gunicorn==23.0.0 qrcode==8.2 pillow==11.3.0 openpyxl==3.1.5
COPY app.py /app/app.py
COPY consumption.py /app/consumption.py
COPY templates /app/templates
COPY static /app/static
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh
EXPOSE 8099
CMD ["/app/run.sh"]
