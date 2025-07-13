# Настройка Google Sheets для аналитики

## 1. Создание Google Form

1. Перейдите на [forms.google.com](https://forms.google.com)
2. Создайте новую форму
3. Добавьте следующие поля:
   - **Timestamp** (автоматически)
   - **User ID** (текст)
   - **Action** (текст)
   - **Project ID** (текст)
   - **Additional Data** (длинный текст)

## 2. Настройка Google Apps Script

1. В Google Form перейдите в "Ответы" → "Google Sheets"
2. Откройте связанную таблицу
3. Перейдите в "Расширения" → "Apps Script"
4. Вставьте следующий код:

```javascript
function doPost(e) {
  try {
    // Получаем данные из запроса
    const data = JSON.parse(e.postData.contents);
    
    // Получаем активную таблицу
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    
    // Добавляем новую строку
    sheet.appendRow([
      new Date(), // Timestamp
      data.user_id || '',
      data.action || '',
      data.project_id || '',
      data.additional_data || ''
    ]);
    
    // Возвращаем успешный ответ
    return ContentService
      .createTextOutput(JSON.stringify({status: 'success'}))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    // Возвращаем ошибку
    return ContentService
      .createTextOutput(JSON.stringify({status: 'error', message: error.toString()}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  return ContentService
    .createTextOutput('Analytics endpoint is working!')
    .setMimeType(ContentService.MimeType.TEXT);
}
```

5. Сохраните скрипт
6. Опубликуйте как веб-приложение:
   - Нажмите "Развернуть" → "Новое развертывание"
   - Выберите тип "Веб-приложение"
   - Установите доступ "Доступно всем"
   - Скопируйте URL

## 3. Настройка переменной окружения

Добавьте в файл `.env`:

```
GOOGLE_SHEETS_WEBHOOK_URL=https://script.google.com/macros/s/YOUR_SCRIPT_ID/exec
```

Замените `YOUR_SCRIPT_ID` на ID вашего скрипта из URL.

## 4. Тестирование

После настройки система будет автоматически отправлять данные о:
- Заданных вопросах
- Подтверждениях отправки форм
- Созданных проектах
- Созданных формах
- Оценках ответов
- Заполненных формах

## 5. Структура данных

Каждая запись содержит:
- **Timestamp**: время события
- **User ID**: ID пользователя Telegram
- **Action**: тип действия (asked_question, confirmed_submission, created_project, etc.)
- **Project ID**: ID проекта (если применимо)
- **Additional Data**: дополнительные данные в JSON формате 