/* Адрес API Нейро-сомелье.
   Прод (vino-terra.ru): пустая строка — nginx проксирует /api на бэкенд с того же домена.
   Локально (localhost/127.0.0.1): main.js сам подставит http://127.0.0.1:8080.
   Если API живёт на другом домене — укажите полный URL, например "https://api.vino-terra.ru". */
window.VINOTERRA_API_URL = "";
