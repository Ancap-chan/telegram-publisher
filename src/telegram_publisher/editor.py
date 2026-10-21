"""Локальное окно визуального редактора публикаций."""

from __future__ import annotations

import sys
from pathlib import Path

import webview


EDITOR_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Редактор публикации</title>
<style>
:root{font:16px "Segoe UI",sans-serif;color:#222;background:#f4f5f7}
body{margin:0;display:flex;flex-direction:column;height:100vh}
header{padding:12px;background:#fff;border-bottom:1px solid #ddd;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
button{font:inherit;padding:7px 10px;border:1px solid #ccc;border-radius:4px;background:#fff;cursor:pointer}
button:hover{background:#eee}
main{flex:1;overflow:auto;padding:24px}
#editor{max-width:900px;min-height:calc(100vh - 150px);margin:0 auto;background:#fff;padding:32px;box-shadow:0 1px 5px #0001;outline:none;line-height:1.55;overflow-wrap:anywhere}
#editor img,#editor video{max-width:100%;height:auto}
#editor table{border-collapse:collapse;width:100%}#editor td,#editor th{border:1px solid #888;padding:6px}
footer{padding:8px 14px;background:#fff;border-top:1px solid #ddd;display:flex;align-items:center;justify-content:space-between}
.status{color:#666;font-size:13px}
.context-menu{position:fixed;z-index:1000;min-width:150px;padding:4px;background:#fff;border:1px solid #bbb;border-radius:5px;box-shadow:0 3px 12px #0002}
.context-menu[hidden]{display:none}
.context-menu button{display:block;width:100%;text-align:left;border:0;background:transparent;padding:7px 10px}
.context-menu button:hover{background:#eee}
</style>
</head>
<body>
<header>
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
<footer><span class="status">Вставка из буфера Ctrl+V сохраняет доступное форматирование. Медиа добавляется по публичному URL.</span><span><button id="cancel">Отмена</button> <button id="save">Сохранить и закрыть</button></span></footer>
<script>
const editor=document.getElementById('editor');
const contextMenu=document.getElementById('context-menu');
editor.innerHTML=window.initialContent||'';
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
document.querySelectorAll('[data-cmd]').forEach(button=>button.addEventListener('click',()=>{
 editor.focus();const cmd=button.dataset.cmd;document.execCommand(cmd,false,button.dataset.value||null);
}));
function askUrl(label){const value=prompt(label,'https://');return value&&/^https?:\/\//i.test(value)?value.trim():null}
document.getElementById('link').onclick=()=>{const url=askUrl('Публичный URL ссылки');if(url){editor.focus();document.execCommand('createLink',false,url)}};
document.getElementById('image').onclick=()=>{const url=askUrl('Публичный URL изображения');if(url){editor.focus();document.execCommand('insertHTML',false,'<p><img src="'+url.replace(/&/g,'&amp;').replace(/"/g,'&quot;')+'" alt=""></p>')}};
document.getElementById('video').onclick=()=>{const url=askUrl('Публичный URL видео');if(url){editor.focus();document.execCommand('insertHTML',false,'<p><video controls src="'+url.replace(/&/g,'&amp;').replace(/"/g,'&quot;')+'"></video></p>')}};
document.getElementById('table').onclick=()=>{const rows=Math.max(1,Math.min(20,Number(prompt('Количество строк','2'))||2));const cols=Math.max(1,Math.min(10,Number(prompt('Количество столбцов','2'))||2));let table='<table><tbody>';for(let r=0;r<rows;r++){table+='<tr>';for(let c=0;c<cols;c++)table+='<td><br></td>';table+='</tr>'}table+='</tbody></table><p><br></p>';editor.focus();document.execCommand('insertHTML',false,table)};
document.getElementById('save').onclick=async()=>{await window.pywebview.api.save_content(editor.innerHTML)};
document.getElementById('cancel').onclick=()=>window.pywebview.api.cancel();
</script>
</body></html>"""


class EditorApi:
    """Передать результат редактора вызывающему приложению."""

    def __init__(self, output_path: Path, window: object) -> None:
        self.output_path = output_path
        self.window = window

    def save_content(self, content: str) -> None:
        self.output_path.write_text(content, encoding="utf-8")
        self.window.destroy()

    def cancel(self) -> None:
        self.window.destroy()


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Нужно указать файлы исходного и итогового HTML.")
    initial_path, output_path = map(Path, sys.argv[1:3])
    initial_content = initial_path.read_text(encoding="utf-8")
    window = webview.create_window("Визуальный редактор публикации", html=EDITOR_HTML, width=1100, height=800)
    api = EditorApi(output_path, window)
    window.expose(api.save_content, api.cancel)

    def initialize() -> None:
        import json
        window.evaluate_js("window.initialContent = " + json.dumps(initial_content, ensure_ascii=False) + "; document.getElementById('editor').innerHTML = window.initialContent;")

    window.events.loaded += initialize
    webview.start(debug=False)


if __name__ == "__main__":
    main()
