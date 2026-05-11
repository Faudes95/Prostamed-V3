import json
import urllib.request
import urllib.error

def test_calculator():
    url = "http://localhost:8080/predict"
    
    # Datos de prueba completos (Post-Op)
    payload = {
        "age": 65,
        "psa": 8.5,
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "clinical_tstage": "T3a",
        "num_cores_positive": 4,
        "total_cores": 12,
        "volumen_prostatico": 45,
        # Post-Op
        "surgical_margin": 1,
        "ece_status": 1,
        "svi_status": 0,
        "lni_status": 0,
        # Default values explicitly set
        "pirads": 1,
        "ecog": 0,
        "cci": 3,
        "ethnicity": "hispanic",
        "family_history": 0,
        "bmi": 27.5
    }
    
    print(f"Enviando solicitud POST a {url}...")
    print(json.dumps(payload, indent=2))
    
    try:
        req = urllib.request.Request(
            url, 
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        
        with urllib.request.urlopen(req) as response:
            status_code = response.getcode()
            response_body = response.read().decode('utf-8')
            
            print(f"\nStatus Code: {status_code}")
            
            if status_code == 200:
                data = json.loads(response_body)
                print("\n✅ CÁLCULO EXITOSO:")
                print("-" * 40)
                
                # Mostrar NCCN
                nccn = data.get('clinical_scores', {}).get('nccn', {})
                print(f"Riesgo NCCN: {nccn.get('risk_group')} ({nccn.get('recomendacion')})")
                
                # Mostrar CAPRA-S
                capra_s = data.get('clinical_scores', {}).get('capra_s', {})
                if capra_s:
                    print(f"CAPRA-S Score: {capra_s.get('score')} ({capra_s.get('risk_group')})")
                    print(f"Supervivencia BCR 5 años: {capra_s.get('bcr_free_survival', {}).get('5y')}%")
                
                # Mostrar Reporte
                print("\n📄 REPORTE NARRATIVO COMPLETO:")
                report = data.get('narrative_report', '')
                print(report)
            else:
                print("\n❌ ERROR:")
                print(response_body)

    except urllib.error.HTTPError as e:
        print(f"\n❌ ERROR HTTP {e.code}:")
        print(e.read().decode('utf-8'))
    except urllib.error.URLError as e:
        print(f"\n❌ ERROR DE CONEXIÓN: {e.reason}")
        print("Asegúrate de que el servidor esté corriendo (python3 app.py)")
    except Exception as e:
        print(f"\n❌ EXCEPCIÓN: {e}")

if __name__ == "__main__":
    test_calculator()
