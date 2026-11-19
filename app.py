import streamlit as st
import json
import time
import base64
import io
import re
import urllib.parse
import requests
import pandas as pd
from PIL import Image
from geopy.geocoders import Nominatim

st.set_page_config(page_title="Organizador de Rotas", page_icon="📦", layout="centered")
st.title("📦 Organizador de Rotas")
st.caption("Misture Mercado Livre, Shopee e Shein em uma única rota otimizada (Agrupa condomínios)")

API_KEY = st.secrets.get("API_KEY", "")
if not API_KEY:
    API_KEY = st.text_input("🔑 Cole sua Chave da API do Google AI Studio:", type="password")

ponto_partida = st.text_input("📍 Endereço de Partida (Galpão ou sua casa):", value="Rua Koesa, 100, Kobrasol, São José - SC")
arquivos = st.file_uploader("📸 Selecione os prints das listas de endereços (ML, Shopee, Shein):", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)

def normalizar_endereco_base(end):
    texto = end.lower().strip()
    texto = re.sub(r'\b(bloco|bl|apto|ap|apartamento|torre|casa|sala|sl|quadra|qd|lote|lt)\b.*', '', texto)
    texto = re.sub(r'[^a-z0-9\s]', '', texto)
    return " ".join(texto.split())

def gerar_links_google_maps(origem, lista_enderecos):
    links = []
    tamanho_bloco = 9
    ponto_atual = origem
    for i in range(0, len(lista_enderecos), tamanho_bloco):
        bloco = lista_enderecos[i:i + tamanho_bloco]
        destino = bloco[-1]
        paradas_intermediarias = bloco[:-1]
        origem_enc = urllib.parse.quote(ponto_atual)
        destino_enc = urllib.parse.quote(destino)
        url = f"https://www.google.com/maps/dir/?api=1&origin={origem_enc}&destination={destino_enc}&travelmode=driving"
        if paradas_intermediarias:
            waypoints_enc = urllib.parse.quote("|".join(paradas_intermediarias))
            url += f"&waypoints={waypoints_enc}"
        links.append((i + 1, i + len(bloco), url))
        ponto_atual = destino
    return links

def ler_lote_gemini(api_key, lote_arquivos):
    prompt = """
    Analise estas capturas de tela de aplicativos de entrega (Mercado Livre, Shopee, Shein).
    Extraia TODOS os pacotes listados e retorne APENAS um array JSON válido, sem texto extra e sem crases de markdown, neste formato exato:
    [{"plataforma": "Mercado Livre ou Shopee ou Shein", "codigo": "4 últimos dígitos do rastreio ou nome do destinatário", "endereco": "Rua, Número, Complemento/Apto, Bairro, Cidade - UF"}]
    """
    partes = [{"text": prompt}]
    for arq in lote_arquivos:
        img = Image.open(arq).convert("RGB")
        img.thumbnail((800, 800))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        partes.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    payload = {
        "contents": [{"parts": partes}],
        "generationConfig": {
            "temperature": 0.1,
            "thinkingConfig": {"thinkingBudget": 0}
        }
    }

    # Vai direto no modelo que respondeu rápido e sem travar
    modelos = ["gemini-3-flash-preview", "gemini-flash-latest"]
    ultimo_erro = ""
    for modelo in modelos:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key.strip()}"
            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code == 200:
                dados = resp.json()
                texto = dados["candidates"][0]["content"]["parts"][0]["text"]
                texto_limpo = texto.replace("```json", "").replace("```", "").strip()
                return json.loads(texto_limpo)
            else:
                ultimo_erro = f"{modelo} ({resp.status_code}): {resp.text}"
        except Exception as err:
            ultimo_erro = f"{modelo}: {err}"
    raise Exception(ultimo_erro)

if st.button("🚀 Organizar Pacotes e Rota", type="primary", use_container_width=True):
    if not API_KEY.strip():
        st.error("⚠️ Cole a sua chave da API na caixinha lá em cima!")
        st.stop()
    if not arquivos:
        st.warning("⚠️ Selecione pelo menos um print de tela antes de apertar o botão.")
        st.stop()

    pacotes_brutos = []
    barra_leitura = st.progress(0, text="🔍 Lendo prints em lotes...")
    tamanho_lote = 2
    total_lotes = (len(arquivos) + tamanho_lote - 1) // tamanho_lote

    try:
        for idx_lote in range(total_lotes):
            lote = arquivos[idx_lote * tamanho_lote : (idx_lote + 1) * tamanho_lote]
            barra_leitura.progress(idx_lote / total_lotes, text=f"🔍 Lendo lote {idx_lote + 1} de {total_lotes} ({len(lote)} prints)...")
            resultado_lote = ler_lote_gemini(API_KEY, lote)
            pacotes_brutos.extend(resultado_lote)
        barra_leitura.progress(1.0, text="✅ Leitura dos prints concluída!")
    except Exception as e:
        st.error(f"Erro ao ler os prints: {e}")
        st.stop()

    vistos = set()
    pacotes = []
    for p in pacotes_brutos:
        chave = f"{p.get('codigo', '').strip().lower()}_{p.get('endereco', '').strip().lower()}"
        if chave not in vistos:
            vistos.add(chave)
            pacotes.append(p)

    if not pacotes:
        st.warning("Nenhum endereço foi identificado nos prints enviados.")
        st.stop()

    grupos_dict = {}
    for p in pacotes:
        chave_base = normalizar_endereco_base(p["endereco"])
        if chave_base not in grupos_dict:
            grupos_dict[chave_base] = {
                "endereco_principal": p["endereco"],
                "pacotes": []
            }
        grupos_dict[chave_base]["pacotes"].append(p)

    paradas_unicas = list(grupos_dict.values())
    st.info(f"📦 {len(pacotes)} pacotes agrupados em {len(paradas_unicas)} parada(s) no mapa!")

    geolocator = Nominatim(user_agent="roteirizador_entregas_brasil_v7")
    try:
        ini = geolocator.geocode(ponto_partida, timeout=10)
    except Exception:
        ini = None
    if not ini:
        st.error("❌ Não encontrei o seu 'Endereço de Partida' no mapa. Tente escrever com Rua, Número, Bairro e Cidade.")
        st.stop()

    coords = [(ini.latitude, ini.longitude)]
    validos = []
    nao_encontrados = []

    barra_mapa = st.progress(0, text="🗺️ Localizando paradas no mapa...")
    total_paradas = len(paradas_unicas)

    for idx, grupo in enumerate(paradas_unicas):
        barra_mapa.progress((idx + 1) / total_paradas, text=f"🗺️ Localizando parada {idx + 1} de {total_paradas}...")
        time.sleep(1.05)
        try:
            loc = geolocator.geocode(grupo["endereco_principal"], timeout=10)
        except Exception:
            loc = None

        if loc:
            coords.append((loc.latitude, loc.longitude))
            validos.append(grupo)
        else:
            nao_encontrados.append(grupo)

    if not validos:
        st.error("❌ Nenhum dos endereços dos prints foi encontrado no mapa.")
        st.stop()

    with st.spinner(f"🚀 Calculando a rota mais curta entre {len(validos)} paradas..."):
        coords_str = ";".join([f"{lon},{lat}" for lat, lon in coords])
        url_osrm = f"http://router.project-osrm.org/trip/v1/driving/{coords_str}?source=first&roundtrip=false"
        try:
            res_osrm = requests.get(url_osrm, timeout=25).json()
            if res_osrm.get("code") == "Ok":
                waypoints = res_osrm["waypoints"]
                ordem = sorted(range(len(waypoints)), key=lambda i: waypoints[i]["waypoint_index"])
                rota_final = [validos[i - 1] for i in ordem if i != 0]
            else:
                rota_final = validos
        except Exception:
            rota_final = validos

        st.session_state["rota_pronta"] = rota_final
        st.session_state["nao_encontrados"] = nao_encontrados
        st.session_state["origem_salva"] = ponto_partida

if "rota_pronta" in st.session_state:
    rota_final = st.session_state["rota_pronta"]
    nao_encontrados = st.session_state["nao_encontrados"]
    origem_salva = st.session_state["origem_salva"]
    total_paradas = len(rota_final)
    total_pacotes = sum(len(g["pacotes"]) for g in rota_final)

    st.success(f"✅ {total_pacotes} pacotes organizados em {total_paradas} paradas!")
    if nao_encontrados:
        with st.expander(f"⚠️ {len(nao_encontrados)} parada(s) não achada(s) no mapa"):
            for ne in nao_encontrados:
                st.write(f"- **{ne['endereco_principal']}** ({len(ne['pacotes'])} pacote(s))")

    aba1, aba2 = st.tabs(["1º Carregar Carro (LIFO)", "2º Ordem de Entrega & GPS"])
    with aba1:
        st.markdown("Escreva o número da parada na caixa com pincel atômico e guarde **de trás para frente** (pacotes do mesmo condomínio ficam juntos):")
        for idx in range(total_paradas, 0, -1):
            grupo = rota_final[idx - 1]
            qtd = len(grupo["pacotes"])
            if idx <= total_paradas * 0.25:
                zona = "🟢 Banco do Carona (Saída Rápida)"
            elif idx <= total_paradas * 0.60:
                zona = "🟡 Banco Traseiro / Meio"
            else:
                zona = "🔴 Fundo do Porta-malas (Últimas entregas)"

            with st.container(border=True):
                col1, col2 = st.columns([1, 2])
                col1.markdown(f"### `#{idx:02d}`")
                col2.markdown(f"**{zona}**")
                if qtd > 1:
                    st.warning(f"🏢 **CONDOMÍNIO / MESMO LOCAL: {qtd} PACOTES JUNTOS!**")
                st.write(f"📍 **{grupo['endereco_principal']}**")
                for p in grupo["pacotes"]:
                    st.write(f"   • 📦 **{p['plataforma']}** | ID/Cliente: `{p['codigo']}` ({p['endereco']})")
                st.checkbox(f"Parada #{idx:02d} ({qtd} pacote(s)) guardada no carro", key=f"chk_{idx}")

    with aba2:
        st.markdown("### 🗺️ Abrir direto no Google Maps (Blocos de 9 paradas)")
        enderecos_ordenados = [g["endereco_principal"] for g in rota_final]
        links_maps = gerar_links_google_maps(origem_salva, enderecos_ordenados)
        for inicio, fim, link in links_maps:
            st.link_button(f"🚗 Navegar Paradas #{inicio:02d} até #{fim:02d} no Google Maps", link, use_container_width=True)
        st.divider()
        linhas_csv = []
        for i, g in enumerate(rota_final):
            for p in g["pacotes"]:
                linhas_csv.append({"Parada": f"#{i+1:02d}", "Plataforma": p["plataforma"], "Identificador": p["codigo"], "Endereco": p["endereco"]})
        df = pd.DataFrame(linhas_csv)
        st.download_button(label="📥 Baixar Planilha para Google My Maps (.csv)", data=df.to_csv(index=False).encode("utf-8-sig"), file_name="rota_mymaps.csv", mime="text/csv", use_container_width=True)
        st.divider()
        st.markdown("### 📋 Lista Corrida de Entregas (#01 até o fim)")
        for idx, grupo in enumerate(rota_final, start=1):
            qtd = len(grupo["pacotes"])
            with st.container(border=True):
                titulo_qtd = f" — **{qtd} PACOTES JUNTOS**" if qtd > 1 else ""
                st.markdown(f"**Parada #{idx:02d}**{titulo_qtd}")
                st.write(f"📍 {grupo['endereco_principal']}")
                for p in grupo["pacotes"]:
                    st.write(f"   • `{p['plataforma']}` ({p['codigo']}) — {p['endereco']}")
