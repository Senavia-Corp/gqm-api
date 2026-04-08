import requests

# Ajusta el puerto si tu API local no corre en el 5000
url = "http://localhost:80/attachments/upload?sync_podio=false" 

# Creamos un archivo de texto virtual "al vuelo" a modo de prueba
files = {
    'file': ('archivo_prueba.txt', 'Contenido del archivo de prueba', 'text/plain')
}

# El FormData que viene del "Frontend"
data = {
    'entity_id': 'PTL6015', # Usa un Job que exista en tu base de datos local
    'year': '2025',
    'access_level': 'members' # Prueba cambiando a "technicians"
}

print(f"Subiendo a Cloudinary (carpeta: {data['access_level']})...")

response = requests.post(url, files=files, data=data)

print(f"Status Code: {response.status_code}")
print("Response JSON:")
print(response.json())
