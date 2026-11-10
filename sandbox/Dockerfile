FROM python:3.12-slim
RUN pip install --no-cache-dir pytest
RUN useradd --create-home runner
WORKDIR /work
USER runner
CMD ["python", "-m", "pytest", "-q"]