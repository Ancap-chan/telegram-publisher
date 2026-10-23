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
.series-break{display:block;position:relative;margin:14px 0;padding:8px 12px;border:2px dashed #789;border-radius:5px;background:#eef3f8;color:#34495e;text-align:center;font-size:13px;cursor:move;user-select:none}.series-break.dragging{opacity:.45}.series-status{padding:8px 14px;background:#f4f5f7;border-bottom:1px solid #ddd;font-size:13px;white-space:pre-wrap}.series-status.warning{color:#a21d1d;font-weight:600}#series-tools{display:none}#series-tools.visible{display:inline-flex;gap:6px;align-items:center}
</style>
</head>
<body>
<header>
<button id="import-url">Импортировать по ссылке</button><button id="import-file">Открыть файл…</button>
<button data-cmd="bold"><b>Жирный</b></button><button data-cmd="italic"><i>Курсив</i></button><button data-cmd="underline"><u>Подчёркнутый</u></button><button data-cmd="strikeThrough"><s>Зачёркнутый</s></button>
<button data-cmd="insertUnorderedList">• Список</button><button data-cmd="insertOrderedList">1. Список</button><button data-cmd="formatBlock" data-value="blockquote">Цитата</button><button data-cmd="formatBlock" data-value="h2" data-rich-only>Заголовок</button><button data-cmd="formatBlock" data-value="p">Абзац</button>
<button id="link">Ссылка</button><button id="image" data-rich-only>Изображение по URL</button><button id="video" data-rich-only>Видео по URL</button><button id="table" data-rich-only>Таблица</button><button data-cmd="removeFormat">Очистить формат</button><span id="series-tools"><button id="insert-break">Разрыв сообщения</button></span>
</header>
<div id="series-status" class="series-status" aria-live="polite" hidden></div><main><div id="editor" contenteditable="true" spellcheck="true"></div></main>
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
 updateModeUI();
 if(modeSelect.value.endsWith('_series'))autoPlaceBreaks();
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
  if(modeSelect.value.endsWith('_series'))autoPlaceBreaks();
  updateModeUI();
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
const seriesStatus=document.getElementById('series-status');
function isSeriesMode(){return modeSelect.value.endsWith('_series')||seriesCheckbox.checked}
function isRichMode(){return modeSelect.value==='rich'||modeSelect.value==='rich_series'||modeSelect.value==='media_text'}
function messageLimit(){return isRichMode()?32768:4096}
function makeBreak(){
 const marker=document.createElement('div');
 marker.className='series-break';
 marker.contentEditable='false';
 marker.draggable=true;
 marker.dataset.postBreak='1';
 marker.textContent='Разрыв сообщения — перетащи, чтобы переместить';
 return marker;
}
function partNodes(){
 const parts=[[]];
 for(const node of Array.from(editor.childNodes)){
  if(node.nodeType===1&&node.classList.contains('series-break')){parts.push([]);continue}
  parts[parts.length-1].push(node);
 }
 return parts;
}
function htmlParts(){
 return partNodes().map(nodes=>{
  const wrapper=document.createElement('div');
  for(const node of nodes)wrapper.appendChild(node.cloneNode(true));
  return wrapper.innerHTML.trim();
 });
}
function partLength(nodes){
 const wrapper=document.createElement('div');
 for(const node of nodes)wrapper.appendChild(node.cloneNode(true));
 wrapper.querySelectorAll('.series-break').forEach(node=>node.remove());
 return (wrapper.innerText||wrapper.textContent||'').trim().length;
}
function updateSeriesStatus(){
 const series=isSeriesMode();
 seriesStatus.hidden=!series;
 if(!series){seriesStatus.textContent='';seriesStatus.classList.remove('warning');return true}
 const parts=partNodes();
 const limit=messageLimit();
 const lengths=parts.map(partLength);
 const overflow=lengths.some(length=>length>limit);
 seriesStatus.classList.toggle('warning',overflow);
 seriesStatus.textContent=lengths.map((length,index)=>'Пост '+(index+1)+': '+length+'/'+limit+' символов'+(length>limit?' — превышен лимит, перенеси часть текста в другой пост.':length===limit?' — лимит заполнен, больше сюда не добавляй; перенеси часть в следующий пост.':'')).join('\n');
 return !overflow;
}
function updateModeUI(){
 const rich=isRichMode();
 document.querySelectorAll('[data-rich-only]').forEach(button=>button.hidden=!rich);
 document.getElementById('series-tools').classList.toggle('visible',isSeriesMode());
 seriesCheckbox.checked=modeSelect.value.endsWith('_series');
 updateSeriesStatus();
}
function autoPlaceBreaks(){
 editor.querySelectorAll('.series-break').forEach(node=>node.remove());
 const limit=messageLimit();
 let used=0;
 for(const node of Array.from(editor.childNodes)){
  const length=(node.innerText||node.textContent||'').trim().length;
  if(used>0&&used+length>limit){editor.insertBefore(makeBreak(),node);used=0}
  used+=length;
 }
 updateSeriesStatus();
}
function insertBreakAtSelection(){
 const selection=window.getSelection();
 let node=selection&&selection.anchorNode;
 while(node&&node.parentNode!==editor)node=node.parentNode;
 const marker=makeBreak();
 if(node&&node.parentNode===editor)editor.insertBefore(marker,node);
 else editor.appendChild(marker);
 updateSeriesStatus();
}
document.getElementById('insert-break').addEventListener('click',insertBreakAtSelection);
editor.addEventListener('input',updateSeriesStatus);
editor.addEventListener('dragstart',event=>{
 const marker=event.target.closest('.series-break');
 if(!marker)return;
 marker.classList.add('dragging');
 event.dataTransfer.setData('text/plain','series-break');
 event.dataTransfer.effectAllowed='move';
});
editor.addEventListener('dragend',event=>{if(event.target.classList)event.target.classList.remove('dragging')});
editor.addEventListener('dragover',event=>{if(isSeriesMode()&&event.target.closest('#editor'))event.preventDefault()});
editor.addEventListener('drop',event=>{
 if(!isSeriesMode()||!event.dataTransfer.types.includes('text/plain'))return;
 const marker=editor.querySelector('.series-break.dragging');
 if(!marker)return;
 event.preventDefault();
 let target=event.target;
 while(target&&target.parentNode!==editor)target=target.parentNode;
 if(target&&target!==marker)editor.insertBefore(marker,event.clientY<target.getBoundingClientRect().top+target.getBoundingClientRect().height/2?target:target.nextSibling);
 else editor.appendChild(marker);
 marker.classList.remove('dragging');
 updateSeriesStatus();
});
modeSelect.addEventListener('change',()=>{
 seriesCheckbox.checked=modeSelect.value.endsWith('_series');
 if(modeSelect.value.endsWith('_series'))autoPlaceBreaks();
 updateModeUI();
});
seriesCheckbox.addEventListener('change',()=>{
 if(seriesCheckbox.checked&&modeSelect.value==='plain')modeSelect.value='plain_series';
 if(seriesCheckbox.checked&&modeSelect.value==='rich')modeSelect.value='rich_series';
 if(!seriesCheckbox.checked&&modeSelect.value.endsWith('_series'))modeSelect.value=modeSelect.value==='plain_series'?'plain':'rich';
 if(modeSelect.value.endsWith('_series'))autoPlaceBreaks();
 updateModeUI();
});
function currentResult(action){
 const series=isSeriesMode();
 const cleanEditor=document.createElement('div');
 for(const node of Array.from(editor.childNodes)){
  if(node.nodeType===1&&node.classList.contains('series-break'))continue;
  cleanEditor.appendChild(node.cloneNode(true));
 }
 return {action,html:cleanEditor.innerHTML,parts:series?htmlParts():[],profile_id:channelSelect.value||null,mode:modeSelect.value,series};
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
 if(isSeriesMode()&&!updateSeriesStatus()){
  document.getElementById('status').textContent='Один или несколько постов превышают лимит. Перенеси часть содержимого или перемести разрыв.';
  return;
 }
 if(!confirm('Опубликовать пост в выбранном канале?'))return;
 const publishButton=document.getElementById('publish');
 publishButton.disabled=true;
 document.getElementById('status').textContent='Подготовка публикации…';
 try{await window.pywebview.api.publish(currentResult('publish'));}
 catch(error){
  publishButton.disabled=false;
  document.getElementById('status').textContent='Не удалось начать публикацию: '+(error&&error.message?error.message:String(error));
 }
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
   if(update.clear){editor.innerHTML='';updateSeriesStatus()}
   if(update.message){
    document.getElementById('status').textContent=update.message;
    if(!update.message.startsWith('Отправка'))document.getElementById('publish').disabled=false;
   }
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
