import django
import socket
from django.core.exceptions import ValidationError
from django.http import JsonResponse


def dns_lookup(domain):
    try:
            ip = socket.gethostbyname(domain)
            
            return {"status": "success", "result": ip}
    except socket.gaierror:
            return {"status": "error", "message": "Host not found or invalid domain."}
    except Exception as e:
            return {"status": "error", "message": str(e)}


# view
def lookup_view(request):
    domain = request.GET.get("domain")
    result = dns_lookup(domain)
    return JsonResponse({"result": result})


