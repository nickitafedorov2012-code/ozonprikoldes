import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import requests
import time
import random
import io

st.set_page_config(page_title="Дашборд Селлера Ozon", layout="wide")

# --- КОНСТАНТЫ И НАСТРОЙКИ ---
API_INFO_URL = "https://api-seller.ozon.ru/v3/product/info/list"
API_ANALYTICS_URL = "https://api-seller.ozon.ru/v1/analytics/data"
API_PERF_URL = "https://performance.ozon.ru/api/client/campaign"


# --- ФУНКЦИИ ПОЛУЧЕНИЯ ДАННЫХ ---
def fetch_ozon_data(client_id: str, api_key: str) -> pd.DataFrame | None:
    """
    Получает реальные данные из API Ozon. 
    Если возникает ошибка или ключи неверны, возвращает None для fallback на демо-данные.
    """
    if not client_id or not api_key:
        return None
        
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json"
    }
    
    # Базовые запросы к API с try-except (в рамках ТЗ - это скелет для будущего расширения)
    try:
        # Пример запроса списка товаров
        payload_info = {
            "offer_id": [],
            "product_id": [],
            "sku": []
        }
        res_info = requests.post(API_INFO_URL, headers=headers, json=payload_info, timeout=5)
        res_info.raise_for_status()
        
        # Здесь должна быть логика объединения с API аналитики и Performance
        # Так как реальных данных нет, если запрос прошел успешно, 
        # все равно пока возвращаем None, чтобы система сгенерировала демо, 
        # либо можно попытаться спарсить. В текущем виде API без валидных ключей 
        # всегда будет падать и переходить на мок.
        
        return None 
    except Exception as e:
        st.sidebar.warning(f"Ошибка API: {e}. Включаем демо-режим.")
        return None

@st.cache_data
def generate_mock_data(cost_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Генерирует демо-данные, имитирующие ответы API. 
    Учитывает загруженную себестоимость, если она есть.
    """
    num_items = 20
    
    skus = [f"SKU-{random.randint(100000, 999999)}" for _ in range(num_items)]
    names = [f"Товар {i+1} (демо)" for i in range(num_items)]
    
    # Генерация или подстановка себестоимости
    costs = []
    if cost_df is not None and not cost_df.empty:
        # Предполагаем, что 1 колонка SKU, 2 колонка Закупочная цена
        sku_col = cost_df.columns[0]
        cost_col = cost_df.columns[1]
        cost_dict = dict(zip(cost_df[sku_col].astype(str), cost_df[cost_col]))
        
        for sku in skus:
            if sku in cost_dict:
                costs.append(float(cost_dict[sku]))
            else:
                costs.append(random.uniform(300, 3000))
    else:
        costs = [random.uniform(300, 3000) for _ in range(num_items)]

    data = []
    for i in range(num_items):
        cost = costs[i]
        price = cost * random.uniform(1.8, 3.5)
        sales_30d = random.randint(0, 300)
        # Добавим крайний случай: продаж нет, но расход есть (для теста подсветки)
        if i == 0:
            sales_30d = 0
            ad_spend = random.uniform(500, 2000)
        else:
            ad_spend = random.uniform(0, 5000) if random.random() > 0.3 else 0
            
        sales_history = [random.randint(0, int(sales_30d/30 * 2) + 1) if sales_30d > 0 else 0 for _ in range(30)]

        data.append({
            "SKU": skus[i],
            "Наименование товара": names[i],
            "Остаток FBO": random.randint(0, 1000),
            "Продажи за 30 дней": sales_30d,
            "Закупочная цена": cost,
            "Комиссия Ozon": price * random.uniform(0.1, 0.2),
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
        
    config['График продаж'] = st.column_config.LineChartColumn("График продаж (30 дн.)")
    config['Целевой ДРР, %'] = st.column_config.NumberColumn("Целевой ДРР, %", format="%.2f %%", min_value=0.0, max_value=100.0, step=1.0)
    
    # Блокируем для редактирования все колонки кроме "Целевой ДРР, %"
    disabled_cols = [col for col in df.columns if col != 'Целевой ДРР, %']
    
    edited_df = st.data_editor(
        styled_df,
        column_config=config,
        disabled=disabled_cols,
        hide_index=True,
        use_container_width=True,
        height=500
    )
    
    st.markdown("### Аналитика")
    
    c1, c2 = st.columns(2)
    
    with c1:
        # Круговая диаграмма (ABC): Распределение чистой прибыли по товарам (только те, что принесли прибыль > 0)
        profit_df = df[df['Чистая прибыль с 1 шт.'] > 0].copy()
        profit_df['Общая прибыль'] = profit_df['Чистая прибыль с 1 шт.'] * (profit_df['Средние продажи в день'] * 30)
        fig_pie = px.pie(profit_df, values='Общая прибыль', names='SKU', title='Распределение чистой прибыли по товарам (ABC)')
        st.plotly_chart(fig_pie, use_container_width=True)
        
    with c2:
        # Точечный график (Матрица риска): X - Оборачиваемость, Y - Текущий ROI, Размер - Остаток FBO, Цвет - Статус товара
        risk_df = df.dropna(subset=['Оборачиваемость в днях', 'Текущий ROI, %']).copy()
        # Для размера точки (остаток FBO) нужно избежать нулевых значений, иначе Plotly выдаст предупреждение/ошибку
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
        st.plotly_chart(fig_scatter, use_container_width=True)
        
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
    st.plotly_chart(fig_heatmap, use_container_width=True)


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
        if raw_data is None:
            if not demo_mode and (client_id or api_key):
                st.sidebar.warning("Не удалось получить данные по API. Переход в демо-режим.")
            raw_data = generate_mock_data(cost_df)
            
        # Расчет метрик
        final_df = process_metrics(raw_data)
        
        # Отображение UI
        build_ui(final_df)

if __name__ == "__main__":
    main()
