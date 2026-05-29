import requests
import urllib3
from dotenv import load_dotenv
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

url = os.getenv("URL_API")
api_key = os.getenv("API_KEY_N8N")

headers = {
    "X-N8N-API-KEY": api_key
}

response = requests.get(
    f"{url}/api/v1/workflows?limit=200",
    headers=headers,
    verify=False
)

workflows = response.json().get("data", [])

SCHEDULE_TYPES = [
    "n8n-nodes-base.scheduleTrigger",
    "n8n-nodes-base.cron",
]

def parse_cron(expr):
    if not expr:
        return "—"
    parts = expr.strip().split()
    if len(parts) < 5:
        return expr
    sec, min_, hour, dom, mon = parts[:5]
    pad = lambda v: str(v).zfill(2)
    if dom != "*" and mon == "*":
        return f"Todo dia {dom} às {pad(hour)}:{pad(min_)}"
    if dom == "*" and mon == "*":
        return f"Diário às {pad(hour)}:{pad(min_)}"
    return expr

resultado = []

for workflow in workflows:
    id_       = workflow.get("id", "—")
    nome      = workflow.get("name", "—")
    ativo     = workflow.get("active", False)
    nodes     = workflow.get("nodes", [])

    sched_nodes = [n for n in nodes if n.get("type") in SCHEDULE_TYPES]

    if not sched_nodes:
        continue

    for node in sched_nodes:
        nome_node  = node.get("name", "—")
        desativado = node.get("disabled", False)

        intervals  = node.get("parameters", {}).get("rule", {}).get("interval", [])

        cron_parts = []
        for i in intervals:
            expr = i.get("expression") or i.get("cronExpression")
            cron_parts.append(expr if expr else "—")
        cron_expr = ", ".join(cron_parts) if cron_parts else "—"

        horario_parts = []
        for i in intervals:
            expr = i.get("expression") or i.get("cronExpression")
            if expr:
                horario_parts.append(parse_cron(expr))
            elif i.get("field") == "hours":
                horario_parts.append(f"A cada {i.get('intervalValue', 1)} hora(s)")
            elif i.get("field") == "minutes":
                horario_parts.append(f"A cada {i.get('intervalValue', 1)} minuto(s)")
            elif i.get("field") == "days":
                horario_parts.append(f"A cada {i.get('intervalValue', 1)} dia(s)")
            else:
                horario_parts.append("—")
        horario = ", ".join(horario_parts) if horario_parts else "—"

        resultado.append({
            "id":            id_,
            "nome":          nome,
            "ativo":         "✅ Sim" if ativo else "❌ Não",
            "nodeSchedule":  nome_node,
            "nodeAtivo":     "❌ Desativado" if desativado else "✅ Ativo",
            "cronExpressao": cron_expr,
            "horario":       horario,
        })

for r in resultado:
    print(r)