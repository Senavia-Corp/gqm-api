FROM python:3.12-slim

# Evitar que Python genere archivos .pyc y habilitar el logeo en tiempo real
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Directorio de trabajo
WORKDIR /app

# Copiar solo requirements primero para aprovechar la caché de Docker
COPY requirements.txt .

# Instalar dependencias
# Se eliminan build-essential y libpq-dev ya que se usa psycopg2-binary
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Exponer el puerto configurado en main.py (80)
EXPOSE 80

# Comando para ejecutar la aplicación
CMD ["python", "main.py"]
