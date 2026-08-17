import secrets

# Las llaves privadas en Ethereum/EVM son 32 bytes de entropía
# representados como una cadena hexadecimal de 64 caracteres.
private_key = secrets.token_hex(32)

print("="*60)
print("🔑 TU LLAVE PRIVADA GENERADA (Guárdala en un lugar seguro):")
print(f"0x{private_key}")
print("="*60)
print("\nPara subirla a Secret Manager en GCP (Sprint 2), ejecuta:")
print("1. Crea un archivo 'tu_llave.txt' y pega ahí tu llave privada (0x...).")
print("2. Ejecuta el comando:")
print("   gcloud secrets versions add WALLET_PRIVATE_KEY --data-file=tu_llave.txt --project=project-d0428141-1b39-47af-9bc")
print("3. Borra el archivo 'tu_llave.txt' de tu máquina.")
