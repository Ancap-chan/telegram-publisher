"""Локальное окно визуального редактора публикаций."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import webview

from .importer import import_from_file, import_from_url


EDITOR_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Редактор публикации</title>
<style>
:root{font:16px "Segoe UI",sans-serif;color:#222;background:#f4f5f7}
*{box-sizing:border-box}
body{margin:0;display:flex;flex-direction:column;height:100vh}
header{padding:10px;background:#fff;border-bottom:1px solid #ddd;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
button,select{font:inherit;padding:7px 10px;border:1px solid #ccc;border-radius:4px;background:#fff;cursor:pointer}
button:hover{background:#eee}
main{flex:1;overflow:auto;padding:24px}
#editor{max-width:1000px;min-height:calc(100vh - 190px);margin:0 auto;background:#fff;padding:32px;box-shadow:0 1px 5px #0001;outline:none;line-height:1.55;overflow-wrap:anywhere}
#editor img,#editor video{max-width:100%;height:auto}
#editor table{border-collapse:collapse;width:100%}
#editor td,#editor th{border:1px solid #888;padding:6px}
footer{padding:10px 14px;background:#fff;border-top:1px solid #ddd;display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.status{color:#555;font-size:13px}
.publish-options{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.context-menu{position:fixed;z-index:1000;min-width:150px;padding:4px;background:#fff;border:1px solid #bbb;border-radius:5px;box-shadow:0 3px 12px #0002}
.context-menu[hidden]{display:none}
.context-menu button{display:block;width:100%;text-align:left;border:0;background:transparent;padding:7px 10px}
.context-menu button:hover{background:#eee}
#publish{font-weight:600}
</style>
</head>
<body>
<header>
<button id="import-url">Импортировать по ссылке</button><button id="import-file">Открыть файл…</button>
<button data-cmd="bold"><b>Жирный</b></button><button data-cmd="italic"><i>Курсив</i></button><button data-cmd="underline"><u>Подчёркнутый</u></button><button data-cmd="strikeThrough"><s>Зачёркнутый</s></button>
<button data-cmd="insertUnorderedList">• Список</button><button data-cmd="insertOrderedList">1. Список</button><button data-cmd="formatBlock" data-value="blockquote">Цитата</button><button data-cmd="formatBlock" data-value="h2">Заголовок</button><button data-cmd="formatBlock" data-value="p">Абзац</button>
<button id="link">Ссылка</button><button id="image">Изображение по URL</button><button id="video">Видео по URL</button><button id="table">Таблица</button><button data-cmd="removeFormat">Очистить формат</button>
</header>
<main><div id="editor" contenteditable="true" spellcheck="true"></div></main>
<div id="context-menu" class="context-menu" hidden>
<button data-edit="cut">Вырезать</button>
<button data-edit="copy">Копировать</button>
<button data-edit="paste">Вставить</button>
</div>
<footer>
<div class="publish-options">
<label for="channel">Канал:</label><select id="channel" aria-label="Канал"></select>
<label for="mode">Способ:</label><select id="mode" aria-label="Способ публикации">
<option value="rich">Рич-текст (с форматированием)</option>
<option value="plain">Обычный текст</option>
<option value="rich_series">Серия рич-сообщений</option>
<option value="plain_series">Серия обычных сообщений</option>
</select>
<label><input id="series" type="checkbox"> Разбить на серию</label>
</div>
<div class="publish-options">
<button id="manage">Настроить каналы…</button>
<button id="cancel">Отмена</button>
<button id="publish">Опубликовать</button>
</div>
<span class="status" id="status">Вставка через Ctrl+V сохраняет доступное форматирование. Изображения и видео можно добавлять по публичному URL.</span>
</footer>
<script>
const editor=document.getElementById('editor');
const contextMenu=document.getElementById('context-menu');
const channelSelect=document.getElementById('channel');
const modeSelect=document.getElementById('mode');
const seriesCheckbox=document.getElementById('series');
let config={profiles:[],selected_profile_id:null,mode:'rich',series:false,status:''};
function applyConfig(value){
 config=value||config;
 editor.innerHTML=window.initialContent||'';
 channelSelect.replaceChildren();
 for(const profile of (config.profiles||[])){
  const option=document.createElement('option');
  option.value=profile.profile_id;
  option.textContent=profile.name+' — '+profile.chat_id;
  channelSelect.append(option);
 }
 if(config.selected_profile_id)channelSelect.value=config.selected_profile_id;
 modeSelect.value=config.mode||'rich';
 seriesCheckbox.checked=Boolean(config.series)||modeSelect.value.endsWith('_series');
 if(!channelSelect.value&&channelSelect.options.length)channelSelect.selectedIndex=0;
 if(config.status)document.getElementById('status').textContent=config.status;
 else if(!channelSelect.options.length)document.getElementById('status').textContent='Сначала настрой канал с помощью кнопки «Настроить каналы…».';
}
function hideContextMenu(){contextMenu.hidden=true}
editor.addEventListener('contextmenu',event=>{
 event.preventDefault();
 contextMenu.hidden=false;
 const x=Math.min(event.clientX,window.innerWidth-contextMenu.offsetWidth-8);
 const y=Math.min(event.clientY,window.innerHeight-contextMenu.offsetHeight-8);
 contextMenu.style.left=Math.max(8,x)+'px';
 contextMenu.style.top=Math.max(8,y)+'px';
});
document.addEventListener('pointerdown',event=>{if(!contextMenu.contains(event.target))hideContextMenu()});
document.addEventListener('keydown',event=>{if(event.key==='Escape')hideContextMenu()});
contextMenu.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',async()=>{
 const action=button.dataset.edit;
 hideContextMenu();
 editor.focus();
 if(action==='cut'||action==='copy'){
  document.execCommand(action,false,null);
  return;
 }
 try{
  if(navigator.clipboard&&navigator.clipboard.read){
   const items=await navigator.clipboard.read();
   for(const item of items){
    if(item.types.includes('text/html')){
     const blob=await item.getType('text/html');
     document.execCommand('insertHTML',false,await blob.text());
     return;
    }
    if(item.types.includes('text/plain')){
     const blob=await item.getType('text/plain');
     document.execCommand('insertText',false,await blob.text());
     return;
    }
   }
  }
  const text=await navigator.clipboard.readText();
  document.execCommand('insertText',false,text);
 }catch(error){
  document.execCommand('paste',false,null);
 }
}));
async function setImportedContent(promise){
 const status=document.getElementById('status');
 status.textContent='Импорт…';
 try{
  const html=await promise;
  if(html===null||html===undefined)return;
  if(!String(html).trim())throw new Error('В источнике не найден текст.');
  editor.innerHTML=html;
  status.textContent='Импорт завершён. Проверь содержимое и при необходимости отредактируй его.';
  editor.focus();
 }catch(error){status.textContent='Не удалось импортировать: '+(error&&error.message?error.message:String(error));}
}
document.getElementById('import-url').onclick=async()=>{
 const url=prompt('Вставь ссылку на публикацию или страницу','https://');
 if(!url)return;
 const trimmedUrl=url.trim();
 if(!trimmedUrl.toLowerCase().startsWith('http://')&&!trimmedUrl.toLowerCase().startsWith('https://')){document.getElementById('status').textContent='Укажи полный URL, начинающийся с http:// или https://.';return;}
 await setImportedContent(window.pywebview.api.import_url(url.trim()));
};
document.getElementById('import-file').onclick=async()=>{
 await setImportedContent(window.pywebview.api.import_file());
};
document.querySelectorAll('[data-cmd]').forEach(button=>button.addEventListener('click',()=>{
 editor.focus();const cmd=button.dataset.cmd;document.execCommand(cmd,false,button.dataset.value||null);
}));
function askUrl(label){const value=prompt(label,'https://');return value&&/^https?:\/\//i.test(value)?value.trim():null}
document.getElementById('link').onclick=()=>{const url=askUrl('Публичный URL ссылки');if(url){editor.focus();document.execCommand('createLink',false,url)}};
document.getElementById('image').onclick=()=>{const url=askUrl('Публичный URL изображения');if(url){editor.focus();document.execCommand('insertHTML',false,'<p><img src="'+url.replace(/&/g,'&amp;').replace(/"/g,'&quot;')+'" alt=""></p>')}};
document.getElementById('video').onclick=()=>{const url=askUrl('Публичный URL видео');if(url){editor.focus();document.execCommand('insertHTML',false,'<p><video controls src="'+url.replace(/&/g,'&amp;').replace(/"/g,'&quot;')+'"></video></p>')}};
document.getElementById('table').onclick=()=>{const rows=Math.max(1,Math.min(20,Number(prompt('Количество строк','2'))||2));const cols=Math.max(1,Math.min(10,Number(prompt('Количество столбцов','2'))||2));let table='<table><tbody>';for(let r=0;r<rows;r++){table+='<tr>';for(let c=0;c<cols;c++)table+='<td><br></td>';table+='</tr>'}table+='</tbody></table><p><br></p>';editor.focus();document.execCommand('insertHTML',false,table)};
modeSelect.addEventListener('change',()=>{if(modeSelect.value.endsWith('_series'))seriesCheckbox.checked=true});
seriesCheckbox.addEventListener('change',()=>{
 if(seriesCheckbox.checked&&modeSelect.value==='plain')modeSelect.value='plain_series';
 if(!seriesCheckbox.checked&&modeSelect.value.endsWith('_series'))modeSelect.value=modeSelect.value==='plain_series'?'plain':'rich';
});
function currentResult(action){
 return {action,html:editor.innerHTML,profile_id:channelSelect.value||null,mode:modeSelect.value,series:seriesCheckbox.checked};
}
document.getElementById('publish').onclick=async()=>{
 if(!channelSelect.value){
  document.getElementById('status').textContent='Выбери канал или сначала настрой его.';
  return;
 }
 const text=editor.innerText.trim();
 if(!text&&!editor.querySelector('img,video')){
  document.getElementById('status').textContent='Добавь текст, изображение или видео перед публикацией.';
  return;
 }
 if(!confirm('Опубликовать пост в выбранном канале?'))return;
 document.getElementById('status').textContent='Подготовка публикации…';
 try{await window.pywebview.api.publish(currentResult('publish'));}
 catch(error){document.getElementById('status').textContent='Не удалось начать публикацию: '+(error&&error.message?error.message:String(error));}
};
document.getElementById('manage').onclick=async()=>{await window.pywebview.api.finish(currentResult('manage_profiles'))};
document.getElementById('cancel').onclick=async()=>{await window.pywebview.api.finish(currentResult('cancel'))};
let statusPolling=false;
async function pollEditorStatus(){
 if(statusPolling||!window.pywebview||!window.pywebview.api)return;
 statusPolling=true;
 try{
  const update=await window.pywebview.api.get_status();
  if(update){
   if(update.clear)editor.innerHTML='';
   if(update.message)document.getElementById('status').textContent=update.message;
  }
 }catch(error){}
 finally{statusPolling=false;}
}
setInterval(pollEditorStatus,500);
window.applyEditorConfig=applyConfig;
</script>
</body></html>"""


class EditorApi:
    """Передать результат редактора вызывающему приложению."""

    def __init__(self, output_path: Path, status_path: Path, window: object) -> None:
        self.output_path = output_path
        self.status_path = status_path
        self.window = window

    def finish(self, result: dict) -> None:
        self.output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        self.window.destroy()

    def publish(self, result: dict) -> None:
        """Передать публикацию основному процессу, не закрывая редактор."""
        self.output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    def get_status(self) -> dict | None:
        """Получить однократное уведомление от основного процесса."""
        try:
            if not self.status_path.is_file():
                return None
            payload = json.loads(self.status_path.read_text(encoding="utf-8"))
            self.status_path.unlink(missing_ok=True)
            return payload if isinstance(payload, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def import_url(self, url: str) -> str:
        """Загрузить публикацию по URL и вернуть HTML для редактора."""
        return import_from_url(url)

    def import_file(self) -> str | None:
        """Предложить выбрать локальный файл и преобразовать его в HTML."""
        paths = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "Поддерживаемые документы (*.txt;*.html;*.htm;*.md;*.markdown;*.docx;*.odt)",
                "Текстовые файлы (*.txt)",
                "HTML (*.html;*.htm)",
                "Markdown (*.md;*.markdown)",
                "Документы Word (*.docx)",
                "Документы OpenDocument (*.odt)",
            ),
        )
        if not paths:
            return None
        return import_from_file(Path(paths[0]))


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("Нужно указать файлы исходного HTML, результата и настроек редактора.")
    initial_path, output_path, config_path = map(Path, sys.argv[1:4])
    initial_content = initial_path.read_text(encoding="utf-8")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    window = webview.create_window(
        "Подготовка и публикация поста",
        html=EDITOR_HTML,
        width=1200,
        height=850,
    )
    status_path = output_path.with_name("editor-status.json")
    status_path.unlink(missing_ok=True)
    api = EditorApi(output_path, status_path, window)
    window.expose(api.finish, api.publish, api.get_status, api.import_url, api.import_file)

    def initialize() -> None:
        window.evaluate_js(
            "window.initialContent = "
            + json.dumps(initial_content, ensure_ascii=False)
            + "; window.applyEditorConfig("
            + json.dumps(config, ensure_ascii=False)
            + ");"
        )

    window.events.loaded += initialize
    webview.start(debug=False)


if __name__ == "__main__":
    main()
