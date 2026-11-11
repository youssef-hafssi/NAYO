/**
 * NAYO — Google Sheet mirror (Apps Script web app).
 * The bot sends every new or changed order here; this script adds the row, or updates it if the
 * order number already exists. Paste it in the sheet: Extensions → Apps Script.
 *
 * SECRET must be identical to SHEET_WEBHOOK_SECRET in the bot's settings (Vercel + bot/.env).
 */
const SECRET = 'PASTE-THE-SHEET_WEBHOOK_SECRET-HERE';
const SHEET_NAME = 'Feuille 1';
const HEADERS = ['order_number', 'created_at', 'name', 'phone', 'quantity', 'total', 'status',
                 'city', 'address', 'whatsapp_from', 'notes', 'updated_at'];

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return json_({ ok: false, error: 'bad json' }); }
  if (body.secret !== SECRET) return json_({ ok: false, error: 'forbidden' });
  const o = body.order || {};
  if (!o.order_number) return json_({ ok: false, error: 'missing order_number' });

  const lock = LockService.getScriptLock();
  lock.waitLock(10000); // two updates at the same time never create duplicate rows
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sh = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);
    if (sh.getLastRow() === 0) {
      sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight('bold');
      sh.setFrozenRows(1);
      sh.getRange('A:L').setNumberFormat('@'); // keep phones / order numbers as text
    }
    const row = HEADERS.map(function (h) { return o[h] === undefined || o[h] === null ? '' : String(o[h]); });
    const last = sh.getLastRow();
    const ids = last > 1 ? sh.getRange(2, 1, last - 1, 1).getDisplayValues().map(function (r) { return r[0]; }) : [];
    const i = ids.indexOf(String(o.order_number));
    if (i >= 0) sh.getRange(i + 2, 1, 1, HEADERS.length).setValues([row]);
    else sh.getRange(last + 1, 1, 1, HEADERS.length).setValues([row]);
  } finally {
    lock.releaseLock();
  }
  return json_({ ok: true });
}

function json_(x) {
  return ContentService.createTextOutput(JSON.stringify(x)).setMimeType(ContentService.MimeType.JSON);
}
