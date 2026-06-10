import requests
import urllib3
import os
from datetime import datetime
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

url     = os.getenv("URL_API")
api_key = os.getenv("API_KEY_N8N")

_gh_repo     = os.getenv("GITHUB_REPOSITORY", "USER/REPO")
GITHUB_USER, GITHUB_REPO = _gh_repo.split("/", 1)

headers = {"X-N8N-API-KEY": api_key}

# ── Coleta com timeout e tratamento de erro ──────────────────────────────────
try:
    response = requests.get(
        f"{url}/api/v1/workflows?limit=200",
        headers=headers,
        verify=False,
        timeout=30,
    )
    response.raise_for_status()
    workflows = response.json().get("data", [])
except requests.exceptions.ConnectTimeout:
    print("Erro: timeout ao conectar no n8n. Servidor inacessível.")
    exit(0)
except requests.exceptions.ConnectionError as e:
    print(f"Erro de conexão: {e}")
    exit(0)
except requests.exceptions.HTTPError as e:
    print(f"Erro HTTP: {e}")
    exit(0)
except requests.exceptions.RequestException as e:
    print(f"Erro ao acessar a API: {e}")
    exit(0)

# ── Tipos de nó de agendamento ───────────────────────────────────────────────
SCHEDULE_TYPES = [
    "n8n-nodes-base.scheduleTrigger",
    "n8n-nodes-base.cron",
]

# ── Tradução de expressão cron ───────────────────────────────────────────────
def traduzir_cron(expr):
    if not expr or expr == "—":
        return "—"

    parts = expr.strip().split()
    if len(parts) == 6:
        # formato com segundos: seg min hora dom mes dow → descarta o campo de segundos
        parts = parts[1:]
    if len(parts) < 5:
        return expr

    minuto, hora, dom, mes, dow = parts[:5]

    dias_semana = {
        "0": "domingo", "1": "segunda", "2": "terça",
        "3": "quarta",  "4": "quinta",  "5": "sexta", "6": "sábado",
        "7": "domingo",
        "SUN": "domingo", "MON": "segunda", "TUE": "terça",
        "WED": "quarta",  "THU": "quinta",  "FRI": "sexta", "SAT": "sábado",
    }

    meses_nome = {
        "1": "janeiro",  "2": "fevereiro", "3":  "março",    "4":  "abril",
        "5": "maio",     "6": "junho",     "7":  "julho",    "8":  "agosto",
        "9": "setembro", "10": "outubro",  "11": "novembro", "12": "dezembro",
    }

    pad = lambda v: str(v).zfill(2)

    # ── A cada N minutos ──────────────────────────────────────────────────────
    if minuto.startswith("*/") and hora == "*" and dom == "*" and mes == "*" and dow == "*":
        n = minuto.split("/")[1]
        return f"A cada {n} minuto(s)"

    # ── A cada N horas ────────────────────────────────────────────────────────
    if hora.startswith("*/") and minuto == "0" and dom == "*" and mes == "*" and dow == "*":
        n = hora.split("/")[1]
        return f"A cada {n} hora(s)"

    # ── Todo dia em horários específicos ──────────────────────────────────────
    if dom == "*" and mes == "*" and dow == "*" and "*" not in minuto and "*" not in hora:
        if "," in hora:
            horas = [f"{pad(h)}:{pad(minuto)}" for h in hora.split(",")]
            return f"Todo dia às {', '.join(horas)}"
        if "," in minuto:
            mins = [f"{pad(hora)}:{pad(m)}" for m in minuto.split(",")]
            return f"Todo dia às {', '.join(mins)}"
        return f"Todo dia às {pad(hora)}:{pad(minuto)}"

    # ── Dia específico do mês ─────────────────────────────────────────────────
    if dom != "*" and mes == "*" and dow == "*" and "*" not in minuto and "*" not in hora:
        return f"Todo dia {dom} do mês às {pad(hora)}:{pad(minuto)}"

    # ── Dias da semana específicos (CORRIGIDO) ────────────────────────────────
    if dow != "*" and dom == "*" and mes == "*" and "*" not in minuto and "*" not in hora:
        dow_original = dow
        
        # Expande intervalos como "1-6" para "1,2,3,4,5,6"
        if "-" in dow and not "," in dow:
            start, end = dow.split("-")
            dow = ",".join(str(d) for d in range(int(start), int(end)+1))
        
        dias = []
        for d in dow.split(","):
            d = d.strip()
            # Traduz números ou nomes de dias
            if d in dias_semana:
                dias.append(dias_semana[d])
            elif d.upper() in dias_semana:
                dias.append(dias_semana[d.upper()])
            else:
                dias.append(d)
        
        # Remove duplicatas mantendo ordem
        dias_unicos = []
        for d in dias:
            if d not in dias_unicos:
                dias_unicos.append(d)
        
        if len(dias_unicos) == 1:
            return f"Toda {dias_unicos[0]} às {pad(hora)}:{pad(minuto)}"
        return f"Toda(s) {', '.join(dias_unicos)} às {pad(hora)}:{pad(minuto)}"

    # ── Dia específico em mês específico ──────────────────────────────────────
    if mes != "*" and dom != "*" and dow == "*" and "*" not in minuto and "*" not in hora:
        # Pode ser número ou nome do mês
        if mes in meses_nome:
            nome_mes = meses_nome[mes]
        elif mes.isdigit() and mes in meses_nome:
            nome_mes = meses_nome[mes]
        else:
            nome_mes = mes
        return f"Todo dia {dom} de {nome_mes} às {pad(hora)}:{pad(minuto)}"

    # ── Caso não identificado, retorna a expressão original ───────────────────
    return expr


# ── Processa workflows ───────────────────────────────────────────────────────
resultado = []

for workflow in workflows:
    id_   = workflow.get("id", "—")
    nome  = workflow.get("name", "—")
    ativo = workflow.get("active", False)
    nodes = workflow.get("nodes", [])

    sched_nodes = [n for n in nodes if n.get("type") in SCHEDULE_TYPES]
    if not sched_nodes:
        continue

    for node in sched_nodes:
        nome_node  = node.get("name", "—")
        desativado = node.get("disabled", False)
        intervals  = node.get("parameters", {}).get("rule", {}).get("interval", [])

        cron_parts, horario_parts = [], []
        for i in intervals:
            expr = (i.get("expression") or i.get("cronExpression") or "").lstrip("=").strip() or None
            cron_parts.append(expr if expr else "—")
            if expr:
                horario_parts.append(traduzir_cron(expr))
            elif i.get("field") == "hours":
                horario_parts.append(f"A cada {i.get('intervalValue', 1)} hora(s)")
            elif i.get("field") == "minutes":
                horario_parts.append(f"A cada {i.get('intervalValue', 1)} minuto(s)")
            elif i.get("field") == "days":
                horario_parts.append(f"A cada {i.get('intervalValue', 1)} dia(s)")
            else:
                horario_parts.append("—")

        # Usa a URL base do .env para o link, ou fallback
        base_url = os.getenv("N8N_URL", url).rstrip("/")
        workflow_url = f"{base_url}/workflow/{id_}"

        resultado.append({
            "id":            workflow_url,
            "nome":          nome,
            "ativo":         True if ativo else False,
            "nodeSchedule":  nome_node,
            "nodeAtivo":     False if desativado else True,
            "cronExpressao": ", ".join(cron_parts)   if cron_parts   else "—",
            "horario":       ", ".join(horario_parts) if horario_parts else "—",
        })

# ── Helpers de badge ─────────────────────────────────────────────────────────
def badge(text, style):
    styles = {
        "green":  "background:#e6f7f0;color:#0a6640;border:1px solid #b3e0cc",
        "red":    "background:#fde8eb;color:#9b1c2e;border:1px solid #f5b0bb",
        "yellow": "background:#fff8e1;color:#7a4f00;border:1px solid #f5d88a",
    }
    return (
        f'<span style="display:inline-flex;align-items:center;gap:4px;'
        f'font-family:monospace;font-size:10px;padding:2px 8px;border-radius:4px;font-weight:600;{styles[style]}">'
        f'<span style="width:5px;height:5px;border-radius:50%;background:currentColor;display:inline-block"></span>'
        f'{text}</span>'
    )

# ── Monta linhas da tabela ───────────────────────────────────────────────────
tr_rows = ""
for r in resultado:
    wf_badge = badge("ATIVO", "green") if r["ativo"] else badge("INATIVO", "red")
    nd_badge = badge("DESATIVADO", "yellow") if not r["nodeAtivo"] else badge("ATIVO", "green")
    tr_rows += f"""
    <tr>
      <td style="font-family:monospace;font-size:11px;color:#8b92a5"><a href="{r['id']}" target="_blank">Link</a></td>
      <td style="color:#1a1d23">{r['nome']}</td>
      <td>{wf_badge}</td>
      <td style="font-family:monospace;font-size:11px;color:#6b7280">{r['nodeSchedule']}</td>
      <td>{nd_badge}</td>
      <td style="font-family:monospace;font-size:11px;color:#4f46e5">{r['cronExpressao']}</td>
      <td style="color:#374151">{r['horario']}</td>
    </tr>"""

total  = len(resultado)
ativos = sum(1 for r in resultado if r["ativo"])
agora  = datetime.now(tz=ZoneInfo("America/Manaus")).strftime("%d/%m/%Y %H:%M:%S")

# ── HTML final ───────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Schedule Triggers — n8n</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #f5f6f8;
    color: #1a1d23;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
    padding: 32px;
  }}
  h1   {{ font-size: 20px; font-weight: 300; margin-bottom: 4px; color: #1a1d23; }}
  h1 b {{ font-weight: 600; color: #111318; }}
  .meta {{ font-family: monospace; font-size: 11px; color: #6b7280; margin-bottom: 24px; }}
  .stats {{ display: flex; gap: 10px; margin-bottom: 20px; }}
  .stat  {{ flex: 1; background: #fff; border: 1px solid #e2e5ec; border-radius: 8px; padding: 10px 14px; }}
  .stat-label {{ font-family: monospace; font-size: 10px; color: #8b92a5; letter-spacing: .1em; text-transform: uppercase; margin-bottom: 4px; }}
  .stat-value {{ font-family: monospace; font-size: 20px; font-weight: 600; }}
  table  {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e2e5ec; border-radius: 10px; overflow: hidden; }}
  thead  {{ background: #f0f2f5; }}
  th     {{ font-family: monospace; font-size: 10px; font-weight: 600; letter-spacing: .12em; color: #6b7280; text-transform: uppercase; padding: 10px 14px; text-align: left; border-bottom: 1px solid #e2e5ec; }}
  tbody tr {{ border-bottom: 1px solid #eef0f4; }}
  tbody tr:last-child {{ border-bottom: none; }}
  tbody tr:hover {{ background: #f7f8fc; }}
  td {{ padding: 10px 14px; vertical-align: middle; }}
  a {{ color: #4f46e5; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  #update-indicator {{
    position: fixed;
    bottom: 16px;
    right: 16px;
    font-family: monospace;
    font-size: 10px;
    color: #8b92a5;
    background: #fff;
    border: 1px solid #e2e5ec;
    border-radius: 6px;
    padding: 4px 10px;
  }}
</style>
</head>
<body>
  <h1><b>Schedule</b> Triggers</h1>
  <p class="meta">Atualizado em: {agora}</p>
  <div class="stats">
    <div class="stat">
      <div class="stat-label">Total</div>
      <div class="stat-value" style="color:#2563eb">{total}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Ativos</div>
      <div class="stat-value" style="color:#0a6640">{ativos}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Inativos</div>
      <div class="stat-value" style="color:#9b1c2e">{total - ativos}</div>
    </div>
  </div>
  <table>
    <thead>
      <tr>
        <th>Link</th>
        <th>Nome do workflow</th>
        <th>Status</th>
        <th>Node schedule</th>
        <th>Node status</th>
        <th>Cron</th>
        <th>Horário</th>
      </tr>
    </thead>
    <tbody>{tr_rows}</tbody>
   </table>

  <div id="update-indicator">⟳ verificando atualizações...</div>

  <script>
    const GITHUB_USER = '{GITHUB_USER}';
    const GITHUB_REPO = '{GITHUB_REPO}';
    const BRANCH = 'main';
    const POLL_INTERVAL = 90000;
    const DEPLOY_DELAY  = 120000;

    const indicator = document.getElementById('update-indicator');
    let lastKnownSha  = null;
    let reloadPending = false;

    async function checkForUpdates() {{
      if (reloadPending) return;

      try {{
        const res = await fetch(
          `https://api.github.com/repos/${{GITHUB_USER}}/${{GITHUB_REPO}}/commits/${{BRANCH}}?t=${{Date.now()}}`,
          {{ headers: {{ 'Accept': 'application/vnd.github.v3+json' }} }}
        );

        if (!res.ok) {{
          indicator.textContent = 'sem conexão';
          return;
        }}

        const sha      = (await res.json()).sha;
        const shortSha = sha.substring(0, 7);

        if (lastKnownSha === null) {{
          lastKnownSha = sha;
          indicator.textContent = `✓ ${{shortSha}} — sincronizado`;
          return;
        }}

        if (sha !== lastKnownSha) {{
          reloadPending = true;
          let remaining = DEPLOY_DELAY / 1000;

          const countdown = setInterval(() => {{
            indicator.textContent = `novo commit detectado, recarregando em ${{remaining}}s...`;
            remaining--;
            if (remaining < 0) clearInterval(countdown);
          }}, 1000);

          setTimeout(() => window.location.reload(), DEPLOY_DELAY);
        }}
      }} catch (e) {{
        indicator.textContent = 'sem conexão';
        console.warn('Erro ao verificar atualização:', e);
      }}
    }}

    setInterval(checkForUpdates, POLL_INTERVAL);
    checkForUpdates();
  </script>
</body>
</html>"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"index.html gerado com {total} workflows.")