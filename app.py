import streamlit as st
import json
import time
import urllib.parse
import requests
import pandas as pd
from PIL import Image
from google import genai
from geopy.geocoders import Nominatim

st.set_page_config(page_title="Organizador de Rotas", page_icon="📦", layout="centered")
st.title("📦 Organizador de Rotas")
st.caption("Misture Mercado Livre, Shopee e Shein em uma única rota otimizada")

API_KEY = st.secrets.get("API_KEY", "")
if not API_KEY:
    API_KEY = st.text_input("🔑 Cole sua Chave da API do Google AI Studio:", type="password")

ponto_partida = st.text_input("📍 Endereço de Partida (Galpão ou sua casa):", value="Rua Koesa, 100, Kobrasol, São José - SC")
arquivos = st.file_uploader("📸 Selecione os prints das listas de endereços (ML, Shopee, Shein):", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)

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

if st.button("🚀 Organizar Pacotes e Rota", type="primary", use_container_width=True):
    if not API_KEY.strip():
        st.error("⚠️ Cole a sua nova chave da API na caixinha lá em cima!")
        st.stop()
    if not arquivos:
        st.warning("⚠️ Selecione pelo menos um print de tela antes de apertar o botão.")
        st.stop()

    with st.spinner("🔍 Lendo endereços e códigos nos prints..."):
        try:
            client = genai.Client(api_key=API_KEY.strip())
            imagens = [Image.open(arq) for arq in arquivos]
            prompt = """
            Analise estas capturas de tela de aplicativos de entrega (Mercado Livre, Shopee, Shein).
            Extraia TODOS os pacotes listados e retorne APENAS um array JSON válido, sem texto extra e sem crases de markdown, neste formato exato:
            [{"plataforma": "Mercado Livre ou Shopee ou Shein", "codigo": "4 últimos dígitos do rastreio ou nome do destinatário", "endereco": "Rua, Número, Bairro, Cidade - UF"}]
            Remova pacotes duplicados caso o mesmo endereço/código apareça em dois prints diferentes.
            """
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=[prompt] + imagens)
            texto_limpo = resp.text.replace("```json", "").replace("```", "").strip()
            pacotes = json.loads(texto_limpo)
        except Exception as e:
            st.error(f"Erro ao ler os prints: {e}")
            st.stop()

    if not pacotes:
        st.warning("Nenhum endereço foi identificado nos prints enviados.")
        st.stop()

    with st.spinner(f"🗺️ Localizando {len(pacotes)} pacotes e calculando o menor trajeto..."):
        geolocator = Nominatim(user_agent="roteirizador_entregas_brasil_v2")
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
        for p in pacotes:
            time.sleep(1)
            try:
                loc = geolocator.geocode(p["endereco"], timeout=10)
                if loc:
                    coords.append((loc.latitude, loc.longitude))
                    validos.append(p)
                else:
                    nao_encontrados.append(p)
            except Exception:
                nao_encontrados.append(p)

        if not validos:
            st.error("❌ Nenhum dos endereços dos prints foi encontrado no mapa.")
            st.stop()

        coords_str = ";".join([f"{lon},{lat}" for lat, lon in coords])
        url_osrm = f"http://router.project-osrm.org/trip/v1/driving/{coords_str}?source=first&roundtrip=false"
        try:
            res_osrm = requests.get(url_osrm, timeout=15).json()
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
    total = len(rota_final)

    st.success(f"✅ {total} pacotes organizados na melhor sequência!")
    if nao_encontrados:
        with st.expander(f"⚠️ {len(nao_encontrados)} endereço(s) não achado(s) no mapa"):
            for ne in nao_encontrados:
                st.write(f"- **{ne['plataforma']}** ({ne['codigo']}): {ne['endereco']}")

    aba1, aba2 = st.tabs(["1º Carregar Carro (LIFO)", "2º Ordem de Entrega & GPS"])
    with aba1:
        st.markdown("Escreva o número grande na caixa com pincel atômico e guarde **de trás para frente**:")
        for idx in range(total, 0, -1):
            p = rota_final[idx - 1]
            if idx <= total * 0.25:
                zona = "🟢 Banco do Carona (Saída Rápida)"
            elif idx <= total * 0.60:
                zona = "🟡 Banco Traseiro / Meio"
            else:
                zona = "🔴 Fundo do Porta-malas (Últimas entregas)"
            with st.container(border=True):
                col1, col2 = st.columns([1, 2])
                col1.markdown(f"### `#{idx:02d}`")
                col2.markdown(f"**{zona}**")
                st.write(f"📦 **{p['plataforma']}** | ID/Cliente: `{p['codigo']}`")
                st.write(f"📍 {p['endereco']}")
                st.checkbox(f"Pacote #{idx:02d} guardado no carro", key=f"chk_{idx}")

    with aba2:
        st.markdown("### 🗺️ Abrir direto no Google Maps")
        enderecos_ordenados = [p["endereco"] for p in rota_final]
        links_maps = gerar_links_google_maps(origem_salva, enderecos_ordenados)
        for inicio, fim, link in links_maps:
            st.link_button(f"🚗 Navegar Paradas #{inicio:02d} até #{fim:02d} no Google Maps", link, use_container_width=True)
        st.divider()
        df = pd.DataFrame([{"Parada": f"#{i+1:02d}", "Plataforma": p["plataforma"], "Identificador": p["codigo"], "Endereco": p["endereco"]} for i, p in enumerate(rota_final)])
        st.download_button(label="📥 Baixar Planilha para Google My Maps (.csv)", data=df.to_csv(index=False).encode("utf-8-sig"), file_name="rota_mymaps.csv", mime="text/csv", use_container_width=True)
        st.divider()
        st.markdown("### 📋 Lista Corrida de Entregas (#01 até o fim)")
        for idx, p in enumerate(rota_final, start=1):
            with st.container(border=True):
                st.markdown(f"**Parada #{idx:02d}** — `{p['plataforma']}` ({p['codigo']})")
                st.write(f"📍 {p['endereco']}")
