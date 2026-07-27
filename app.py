import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import requests
import time
import random
import io
import warnings
import logging
from logging.handlers import RotatingFileHandler

# Подавляем предупреждение openpyxl о стилях по умолчанию
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

# Настраиваем логирование в файл
logger = logging.getLogger("OzonDashboard")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler("ozon_dashboard.log", maxBytes=1024*1024*5, backupCount=2)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)

st.set_page_config(page_title="Дашборд Селлера Ozon", layout="wide")

# --- КОНСТАНТЫ И НАСТРОЙКИ ---
API_LIST_URL = "https://api-seller.ozon.ru/v3/product/list"
API_INFO_URL = "https://api-seller.ozon.ru/v3/product/info/list"
API_ANALYTICS_URL = "https://api-seller.ozon.ru/v1/analytics/data"
API_PERF_URL = "https://performance.ozon.ru/api/client/campaign"


# --- ФУНКЦИИ ПОЛУЧЕНИЯ ДАННЫХ ---
def fetch_ozon_data(client_id: str, api_key: str) -> dict | None:
    """
    Получает реальные данные из API Ozon. 
    Возвращает словарь с данными (например, список реальных SKU), 
    или None, если произошла ошибка.
    """
    if not client_id or not api_key:
        return None
        
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json"
    }
    
    try:
        # 1. Сначала получаем список всех реальных product_id магазина (с пагинацией)
        all_product_ids = []
        all_items_basic = []
        last_id = ""
        limit = 1000  # API Ozon позволяет limit до 1000 для product/list
        
        while True:
            payload_list = {
                "filter": {
                    "visibility": "ALL"
                },
                "limit": limit,
                "last_id": last_id,
            }
            res_list = requests.post(API_LIST_URL, headers=headers, json=payload_list, timeout=15)
            res_list.raise_for_status()
            
            data_list = res_list.json().get('result', {})
            items = data_list.get('items', [])
            
            if not items:
                break
                
            all_items_basic.extend(items)
            all_product_ids.extend([item['product_id'] for item in items])
            
            last_id = data_list.get('last_id', "")
            # Если last_id пустой или мы получили меньше лимита, значит это последняя страница
            if not last_id or len(items) < limit:
                break
        
        if not all_product_ids:
            st.sidebar.success("Авторизация успешна, но у вас пока нет товаров.")
            return {"real_skus": [], "real_names": []}
            
        # 2. Получаем детальную информацию по этим товарам (батчами)
        # Ozon info/list рекомендует передавать не более 100 ID за раз
        chunk_size = 100
        real_skus = []
        real_names = []
        
        for i in range(0, len(all_product_ids), chunk_size):
            chunk_ids = all_product_ids[i:i + chunk_size]
            payload_info = {
                "product_id": chunk_ids
            }
            try:
                res_info = requests.post(API_INFO_URL, headers=headers, json=payload_info, timeout=15)
                res_info.raise_for_status()
                
                info_data = res_info.json().get('result', {})
                info_items = info_data.get('items', []) if isinstance(info_data, dict) else info_data
                
                if info_items:
                    for item in info_items:
                        # Извлекаем подробные данные
                        sku = item.get('offer_id', f"SKU-{item.get('product_id')}")
                        real_skus.append(sku)
                        real_names.append(item.get('name', "Без названия"))
                        
                        # Парсинг цены
                        price_str = item.get('price', "0")
                        try:
                            price = float(price_str)
                        except:
                            price = 0.0
                            
                        # Парсинг остатков (stocks) - часто в v3 info/list есть массив stocks
                        stocks = item.get('stocks', [])
                        fbo_stock = 0
                        if isinstance(stocks, list):
                            for stock_info in stocks:
                                if stock_info.get('has_stock'):
                                    fbo_stock += int(stock_info.get('present', 0))
                        
                        # Парсинг комиссий (если отдаются)
                        commissions = item.get('commissions', {})
                        fbo_comm = 0.0
                        if isinstance(commissions, dict):
                            fbo_comm = float(commissions.get('fbo_deliv_to_customer_amount', 0)) + float(commissions.get('sales_percent_fbo', 0))

                        # Сохраняем в dict
                        item_data = {
                            "name": item.get('name', "Без названия"),
                            "price": price,
                            "fbo_stock": fbo_stock,
                            "commission": fbo_comm
                        }
                        # Используем общий словарь в raw_data для хранения деталей
                        if 'details' not in locals():
                            details = {}
                        details[sku] = item_data
                        
            except Exception as e:
                logger.error(f"Ошибка при загрузке чанка {i}: {e}")
                # Если детальки не загрузились, используем fallback
                continue
                
        if 'details' not in locals():
            details = {}

        # Fallback для тех товаров, которые не смогли получить детальную инфу
        if len(real_skus) < len(all_product_ids):
            loaded_ids = set([s.replace("SKU-", "") for s in real_skus])
            for item in all_items_basic:
                if str(item['product_id']) not in loaded_ids and item.get('offer_id') not in real_skus:
                    sku = item.get('offer_id', f"SKU-{item.get('product_id')}")
                    real_skus.append(sku)
                    real_names.append(f"Товар {item.get('product_id')} (без названия)")
                    details[sku] = {
                        "name": f"Товар {item.get('product_id')} (без названия)",
                        "price": 0.0,
                        "fbo_stock": 0,
                        "commission": 0.0
                    }
            
        st.sidebar.success(f"API подключено! Загружено {len(real_skus)} товаров.")
        logger.info(f"Успешно загружено {len(real_skus)} товаров через API")
        
        return {"real_skus": real_skus, "real_names": real_names, "details": details}
        
    except requests.exceptions.RequestException as e:
        st.sidebar.warning(f"Ошибка HTTP запроса: {e}. Включаем демо-режим.")
        err_text = getattr(e.response, 'text', 'Нет деталей')
        logger.error(f"Ошибка HTTP: {e} - {err_text}")
        if hasattr(e, 'response') and e.response is not None:
            st.sidebar.code(f"Детали ошибки от сервера:\n{e.response.text}")
        return None
    except Exception as e:
        st.sidebar.warning(f"Внутренняя ошибка API: {e}. Включаем демо-режим.")
        logger.error(f"Внутренняя ошибка API: {e}", exc_info=True)
        return None

@st.cache_data
def generate_mock_data(cost_df: pd.DataFrame | None = None, api_data: dict | None = None) -> pd.DataFrame:
    """
    Генерирует демо-данные, имитирующие ответы API. 
    Учитывает загруженную себестоимость и реальные SKU, если они есть.
    """
    details = {}
    if api_data and api_data.get("real_skus"):
        skus = api_data["real_skus"]
        names = api_data["real_names"]
        details = api_data.get("details", {})
        num_items = len(skus)
    else:
        num_items = 20
        skus = [f"SKU-{random.randint(100000, 999999)}" for _ in range(num_items)]
        names = [f"Товар {i+1} (демо)" for i in range(num_items)]
    
    # Генерация или подстановка себестоимости
    costs = []
    cost_dict = {}
    if cost_df is not None and not cost_df.empty:
        # Пытаемся найти колонку артикула по ключевым словам
        sku_col_name = next((col for col in cost_df.columns if 'артикул' in str(col).lower() or 'sku' in str(col).lower()), None)
        # Пытаемся найти колонку цены по ключевым словам ('закупочная', 'себестоимость')
        cost_col_name = next((col for col in cost_df.columns if 'закупочная' in str(col).lower() or 'себестоимость' in str(col).lower()), None)
        
        # Если не нашли, берем 1 и 2 колонки как fallback (исходное поведение)
        if not sku_col_name or not cost_col_name:
             sku_col_name = cost_df.columns[0]
             cost_col_name = cost_df.columns[1]

        # Очищаем данные от нечисловых символов (например " руб", "р.", пробелы) и конвертируем во float
        def clean_price(val):
            try:
                if isinstance(val, (int, float)):
                    return float(val)
                import re
                val_str = str(val).replace(',', '.')
                cleaned = re.sub(r'[^\d.]', '', val_str)
                return float(cleaned) if cleaned else 0.0
            except:
                return 0.0

        cost_df[cost_col_name] = cost_df[cost_col_name].apply(clean_price)
        cost_dict = dict(zip(cost_df[sku_col_name].astype(str).str.strip(), cost_df[cost_col_name]))
        
        for sku in skus:
            # Если SKU есть в загруженном файле, берем его цену, иначе случайную из файла
            if sku in cost_dict:
                costs.append(float(cost_dict[sku]))
            elif cost_dict:
                costs.append(random.choice(list(cost_dict.values())))
            else:
                costs.append(random.uniform(300, 3000))
    else:
        costs = [random.uniform(300, 3000) for _ in range(num_items)]

    data = []
    for i in range(num_items):
        sku = skus[i]
        cost = costs[i]
        
        # Берем реальные детали, если они есть
        item_details = details.get(sku, {})
        
        # Если API отдал реальную цену > 0, используем её. Иначе мокаем.
        real_price = item_details.get('price', 0)
        price = real_price if real_price > 0 else cost * random.uniform(1.8, 3.5)
        
        # Реальные остатки (если не было в API, мокаем)
        fbo_stock = item_details.get('fbo_stock', None)
        if fbo_stock is None:
            fbo_stock = random.randint(0, 1000)
            
        # Реальная комиссия (если отдана, иначе мокаем)
        real_comm = item_details.get('commission', 0)
        comm_ozon = real_comm if real_comm > 0 else price * random.uniform(0.1, 0.2)
        
        # Мокаем продажи и рекламу
        sales_30d = random.randint(0, 300)
        # Добавим крайний случай: продаж нет, но расход есть (для теста подсветки)
        if i == 0:
            sales_30d = 0
            ad_spend = random.uniform(500, 2000)
        else:
            ad_spend = random.uniform(0, 5000) if random.random() > 0.3 else 0
            
        sales_history = [random.randint(0, int(sales_30d/30 * 2) + 1) if sales_30d > 0 else 0 for _ in range(30)]

        data.append({
            "SKU": sku,
            "Наименование товара": item_details.get('name', names[i]),
            "Остаток FBO": fbo_stock,
            "Продажи за 30 дней": sales_30d,
            "Закупочная цена": cost,
            "Комиссия Ozon": comm_ozon,
            "Логистика Ozon": random.uniform(50, 150),
            "Эквайринг": price * 0.015,
            "Текущая цена продажи": price,
            "Участвует в продвижении": "Да" if ad_spend > 0 else "Нет",
            "ID кампании": f"CMP-{random.randint(1000, 9999)}" if ad_spend > 0 else None,
            "Расход за месяц": ad_spend,
            "График продаж": sales_history
        })
        
    return pd.DataFrame(data)


# --- РАСЧЕТ МЕТРИК ---
def process_metrics(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Рассчитывает все метрики строго по заданным формулам с защитой от деления на ноль.
    """
    df = raw_df.copy()
    
    # C. Площадка
    df['Площадка'] = "OZON"
    
    # E. Средние продажи в день
    df['Средние продажи в день'] = df['Продажи за 30 дней'] / 30.0
    
    # F. Оборачиваемость в днях
    def calc_turnover(row):
        e = row['Средние продажи в день']
        d = row['Остаток FBO']
        return d / e if e > 0 else None
    df['Оборачиваемость в днях'] = df.apply(calc_turnover, axis=1)
    
    # G. Скоринг оборачиваемости (0-100)
    def calc_scoring(row):
        f = row['Оборачиваемость в днях']
        if pd.isna(f) or f == 0:
            return None
        return max(0, min(100, (150 - f) / 1.2))
    df['Скоринг оборачиваемости'] = df.apply(calc_scoring, axis=1)
    
    # H. Себестоимость + все расходы на 1 шт.
    df['Себестоимость + расходы'] = (df['Закупочная цена'] + 
                                     df['Комиссия Ozon'] + 
                                     df['Логистика Ozon'] + 
                                     df['Эквайринг'])
                                     
    # I. Текущая цена продажи (уже есть)
    
    # J. Чистая прибыль с 1 шт.
    df['Чистая прибыль с 1 шт.'] = df['Текущая цена продажи'] - df['Себестоимость + расходы']
    
    # K. ДРР, %: Целевой ДРР
    if 'Целевой ДРР, %' not in df.columns:
        df['Целевой ДРР, %'] = 10.0
        
    # L. Текущий ROI, %
    df['Текущий ROI, %'] = (df['Чистая прибыль с 1 шт.'] / df['Себестоимость + расходы']) * 100
    
    # M. Текущий ДРР, %
    def calc_current_drr(row):
        e = row['Средние продажи в день']
        if e == 0:
            return 0.0
        r = row['Расход за месяц']
        i = row['Текущая цена продажи']
        if i == 0:
            return 0.0
        return ((r / (e * 30)) / i) * 100
    df['Текущий ДРР, %'] = df.apply(calc_current_drr, axis=1)
    
    # N. Макс. ДРР, % (для ROI 60%)
    def calc_max_drr(row):
        i = row['Текущая цена продажи']
        h = row['Себестоимость + расходы']
        if i == 0:
            return 0.0
        return max(0, ((i - (h * 1.60)) / i) * 100)
    df['Макс. ДРР, % (для ROI 60%)'] = df.apply(calc_max_drr, axis=1)
    
    # Q. ROI с учетом текущего ДРР, %
    def calc_roi_with_drr(row):
        e = row['Средние продажи в день']
        if e == 0:
            return 0.0
        r = row['Расход за месяц']
        j = row['Чистая прибыль с 1 шт.']
        h = row['Себестоимость + расходы']
        if h == 0:
            return 0.0
        return ((j - (r / (e * 30))) / h) * 100
    df['ROI с учетом текущего ДРР, %'] = df.apply(calc_roi_with_drr, axis=1)
    
    # S. Минимальная цена (для ROI 60%)
    df['Минимальная цена (ROI 60%)'] = df['Себестоимость + расходы'] * 1.60
    
    # U. Балл риска (0-10)
    def calc_risk_score(row):
        g = row['Скоринг оборачиваемости']
        if pd.isna(g):
            return None
        return (100 - g) / 10.0
    df['Балл риска (0-10)'] = df.apply(calc_risk_score, axis=1)
    
    # V. Статус товара
    def calc_status(row):
        u = row['Балл риска (0-10)']
        if pd.isna(u):
            return "⚪ Неизвестно"
        if u <= 3.3:
            return "🟢 Отлично"
        elif u <= 6.6:
            return "🟡 Внимание"
        else:
            return "🔴 Критично"
    df['Статус товара'] = df.apply(calc_status, axis=1)
    
    # Переупорядочим столбцы для удобства
    columns_order = [
        'SKU', 'Наименование товара', 'Площадка', 'Остаток FBO', 
        'Средние продажи в день', 'Оборачиваемость в днях', 'Скоринг оборачиваемости',
        'Себестоимость + расходы', 'Текущая цена продажи', 'Чистая прибыль с 1 шт.',
        'Целевой ДРР, %', 'Текущий ROI, %', 'Текущий ДРР, %', 'Макс. ДРР, % (для ROI 60%)',
        'Участвует в продвижении', 'ID кампании', 'ROI с учетом текущего ДРР, %',
        'Расход за месяц', 'Минимальная цена (ROI 60%)', 'График продаж',
        'Балл риска (0-10)', 'Статус товара'
    ]
    
    return df[columns_order]


# --- UI И ВИЗУАЛИЗАЦИЯ ---
def build_ui(df: pd.DataFrame):
    st.title("Дашборд Селлера Ozon")
    
    # 2. Главный экран (Метрики)
    # Выручка за 30 дней: Сумма (Текущая цена * Продажи за 30 дней) - приблизительно, так как цена текущая
    # Для точной выручки умножим средние продажи в день * 30 * текущую цену
    revenue_30d = (df['Средние продажи в день'] * 30 * df['Текущая цена продажи']).sum()
    
    # Чистая прибыль (за 30 дней): Сумма (Чистая прибыль с 1 шт * Продажи за 30 дней)
    profit_30d = (df['Чистая прибыль с 1 шт.'] * df['Средние продажи в день'] * 30).sum()
    
    # Замороженные деньги в FBO: Остаток FBO * Себестоимость+расходы
    frozen_fbo = (df['Остаток FBO'] * df['Себестоимость + расходы']).sum()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Выручка за 30 дней", f"{revenue_30d:,.2f} ₽".replace(",", " "))
    col2.metric("Чистая прибыль (30 дн.)", f"{profit_30d:,.2f} ₽".replace(",", " "))
    col3.metric("Замороженные деньги FBO", f"{frozen_fbo:,.2f} ₽".replace(",", " "))
    
    st.markdown("### Данные по товарам")
    
    # Стилизация таблицы (подсветка строки красным, если E == 0 и R > 0)
    def style_dataframe(row):
        if row['Средние продажи в день'] == 0 and row['Расход за месяц'] > 0:
            return ['background-color: rgba(255, 0, 0, 0.2)'] * len(row)
        return [''] * len(row)
    
    styled_df = df.style.apply(style_dataframe, axis=1)
    
    # Настройка колонок для st.data_editor
    # Денежные значения: H, I, J, R, S
    # Проценты: K, L, M, N, Q
    currency_cols = ['Себестоимость + расходы', 'Текущая цена продажи', 'Чистая прибыль с 1 шт.', 
                     'Расход за месяц', 'Минимальная цена (ROI 60%)']
    percent_cols = ['Целевой ДРР, %', 'Текущий ROI, %', 'Текущий ДРР, %', 
                    'Макс. ДРР, % (для ROI 60%)', 'ROI с учетом текущего ДРР, %']
    
    config = {}
    for col in currency_cols:
        config[col] = st.column_config.NumberColumn(col, format="%.2f ₽")
    for col in percent_cols:
        config[col] = st.column_config.NumberColumn(col, format="%.2f %%")
        
    # Форматирование остальных числовых колонок
    config['Средние продажи в день'] = st.column_config.NumberColumn("Средние продажи в день", format="%.2f")
    config['Оборачиваемость в днях'] = st.column_config.NumberColumn("Оборачиваемость в днях", format="%.1f")
    config['Скоринг оборачиваемости'] = st.column_config.NumberColumn("Скоринг оборачиваемости", format="%.1f")
    config['Балл риска (0-10)'] = st.column_config.NumberColumn("Балл риска (0-10)", format="%.1f")
        
    config['График продаж'] = st.column_config.LineChartColumn("График продаж (30 дн.)")
    config['Целевой ДРР, %'] = st.column_config.NumberColumn("Целевой ДРР, %", format="%.2f %%", min_value=0.0, max_value=100.0, step=1.0)
    
    # Блокируем для редактирования все колонки кроме "Целевой ДРР, %"
    disabled_cols = [col for col in df.columns if col != 'Целевой ДРР, %']
    
    edited_df = st.data_editor(
        styled_df,
        column_config=config,
        disabled=disabled_cols,
        hide_index=True,
        width="stretch",
        height=500
    )
    
    st.markdown("### Аналитика")
    
    c1, c2 = st.columns(2)
    
    with c1:
        # Круговая диаграмма (ABC): Распределение чистой прибыли по товарам (только те, что принесли прибыль > 0)
        profit_df = df[df['Чистая прибыль с 1 шт.'] > 0].copy()
        if not profit_df.empty:
            profit_df['Общая прибыль'] = profit_df['Чистая прибыль с 1 шт.'] * (profit_df['Средние продажи в день'] * 30)
            fig_pie = px.pie(profit_df, values='Общая прибыль', names='SKU', title='Распределение чистой прибыли по товарам (ABC)')
            st.plotly_chart(fig_pie, width="stretch")
        else:
            st.info("Нет товаров с положительной чистой прибылью для отображения графика ABC.")
        
    with c2:
        # Точечный график (Матрица риска): X - Оборачиваемость, Y - Текущий ROI, Размер - Остаток FBO, Цвет - Статус товара
        risk_df = df.dropna(subset=['Оборачиваемость в днях', 'Текущий ROI, %']).copy()
        if not risk_df.empty:
            risk_df['Размер_Точки'] = risk_df['Остаток FBO'].apply(lambda x: x if x > 0 else 1)
            
            color_map = {
                "🟢 Отлично": "green",
                "🟡 Внимание": "yellow",
                "🔴 Критично": "red",
                "⚪ Неизвестно": "gray"
            }
            
            fig_scatter = px.scatter(
                risk_df, 
                x='Оборачиваемость в днях', 
                y='Текущий ROI, %', 
                size='Размер_Точки',
                color='Статус товара',
                color_discrete_map=color_map,
                hover_name='SKU',
                title='Матрица риска: Оборачиваемость vs ROI'
            )
            st.plotly_chart(fig_scatter, width="stretch")
        else:
            st.info("Недостаточно данных для построения матрицы риска.")
        
    # Хитмап (Корреляция): Корреляционная матрица между ценой, ROI, текущим ДРР и Скорингом
    st.markdown("#### Корреляционная матрица")
    corr_cols = ['Текущая цена продажи', 'Текущий ROI, %', 'Текущий ДРР, %', 'Скоринг оборачиваемости']
    corr_df = df[corr_cols].corr()
    
    fig_heatmap = px.imshow(
        corr_df, 
        text_auto=".2f", 
        color_continuous_scale='RdBu_r', 
        zmin=-1, zmax=1,
        title="Корреляция: Цена, ROI, ДРР, Скоринг"
    )
    st.plotly_chart(fig_heatmap, width="stretch")


# --- ТОЧКА ВХОДА ---
def main():
    # 1. Сайдбар
    st.sidebar.title("Настройки")
    
    client_id = st.sidebar.text_input("Client ID", type="password")
    api_key = st.sidebar.text_input("API Key", type="password")
    
    cost_file = st.sidebar.file_uploader("Файл себестоимости (CSV/Excel)", type=["csv", "xlsx"])
    
    demo_mode = st.sidebar.toggle("Демо-режим", value=True)
    update_btn = st.sidebar.button("Обновить данные")
    
    # Обработка файла себестоимости
    cost_df = None
    if cost_file is not None:
        try:
            if cost_file.name.endswith(".csv"):
                cost_df = pd.read_csv(cost_file)
            else:
                cost_df = pd.read_excel(cost_file)
        except Exception as e:
            st.sidebar.error(f"Ошибка чтения файла: {e}")
            
    # Получение или генерация данных
    raw_data = None
    
    if update_btn or True: # Отрисовываем по умолчанию
        if not demo_mode and client_id and api_key:
            with st.spinner("Загрузка данных из API..."):
                raw_data = fetch_ozon_data(client_id, api_key)
        
        # Fallback к демо-режиму
        # Если raw_data является словарем (успешный ответ API), 
        # нам нужно сгенерировать DataFrame на основе этих SKU (гибридный демо-режим)
        if isinstance(raw_data, dict):
            raw_data = generate_mock_data(cost_df, raw_data)
        elif raw_data is None:
            if not demo_mode and (client_id or api_key):
                st.sidebar.warning("Не удалось получить данные по API. Переход в демо-режим.")
            raw_data = generate_mock_data(cost_df)
            
        # Если после генерации данных нет
        if raw_data.empty:
            st.info("Нет данных для отображения.")
            return

        # Расчет метрик
        final_df = process_metrics(raw_data)
        
        # Отображение UI
        build_ui(final_df)

if __name__ == "__main__":
    main()
