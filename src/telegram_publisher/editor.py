"""Локальное окно визуального редактора публикаций."""

from __future__ import annotations

import json
import sys
import re
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
header{padding:10px;background:#fff;border-bottom:1px solid #ddd;display:flex;flex-direction:column;gap:8px;align-items:stretch}.toolbar-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;width:100%}.heading-tool{padding:4px 7px;font-size:12px;min-width:34px}.plain-unsupported{outline:2px dashed #c87919!important;background-color:#fff3d8!important}.plain-unsupported::after{content:"";display:inline-block}
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
.series-break{display:block;position:relative;margin:14px 0;padding:8px 12px;border:2px dashed #789;border-radius:5px;background:#eef3f8;color:#34495e;text-align:center;font-size:13px;cursor:default;user-select:none}.series-break.selected{outline:2px solid #2457a7;background:#dce8fa}.series-status{padding:8px 14px;background:#f4f5f7;border-bottom:1px solid #ddd;font-size:13px;white-space:pre-wrap}.series-status.warning{color:#a21d1d;font-weight:600}#series-tools{display:none}#series-tools.visible{display:inline-flex;gap:6px;align-items:center}
</style>
</head>
<body>
<header>
<div class="toolbar-row file-tools"><button id="import-url">Импортировать по ссылке</button><button id="import-file">Открыть файл…</button><button id="save-draft">Сохранить черновик…</button><button id="manual" style="margin-left:auto">Руководство</button></div>
<div class="toolbar-row edit-tools"><button data-cmd="bold"><b>Жирный</b></button><button data-cmd="italic"><i>Курсив</i></button><button data-cmd="underline"><u>Подчёркнутый</u></button><button data-cmd="strikeThrough"><s>Зачёркнутый</s></button>
<button data-cmd="insertUnorderedList">• Список</button><button data-cmd="insertOrderedList">1. Список</button><button data-cmd="formatBlock" data-value="blockquote">Цитата</button><button class="heading-tool" data-cmd="formatBlock" data-value="h1" data-rich-only>H1</button><button class="heading-tool" data-cmd="formatBlock" data-value="h2" data-rich-only>H2</button><button class="heading-tool" data-cmd="formatBlock" data-value="h3" data-rich-only>H3</button><button class="heading-tool" data-cmd="formatBlock" data-value="h4" data-rich-only>H4</button><button class="heading-tool" data-cmd="formatBlock" data-value="h5" data-rich-only>H5</button><button class="heading-tool" data-cmd="formatBlock" data-value="h6" data-rich-only>H6</button><button data-cmd="formatBlock" data-value="p">Абзац</button>
<button id="link">Ссылка</button><button id="media">Медиа по URL</button><button id="table" data-rich-only>Таблица</button><button data-cmd="removeFormat">Очистить формат</button><span id="series-tools"><button id="insert-break">Разрыв сообщения</button></span></div>
</header>
<div id="series-status" class="series-status" aria-live="polite" hidden></div><main><div id="editor" contenteditable="true" spellcheck="true"></div></main>
<div id="context-menu" class="context-menu" hidden>
<button data-edit="cut">Вырезать</button>
<button data-edit="copy">Копировать</button>
<button data-edit="paste">Вставить</button>
<button data-action="insert-break">Вставить разрыв сообщения</button>
<button data-action="delete-break">Удалить разрыв</button>
</div>
<footer>
<div class="publish-options">
<label for="channel">Канал:</label><select id="channel" aria-label="Канал"></select>
<label for="mode">Способ публикации:</label><select id="mode" aria-label="Способ публикации">
<option value="rich">Рич-сообщение (полноценное форматирование, размер до 32768 символов)</option>
<option value="plain">Обычное сообщение (минимальное форматирование, размер до 4096 символов)</option>
<option value="rich_series">Серия рич-сообщений</option>
<option value="plain_series">Серия обычных сообщений</option>
</select>
<label><input id="series" type="checkbox"> Разбить на серию постов</label>
</div>
<div class="publish-options">
<button id="manage">Настроить каналы…</button>
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
let savedRange=null;
let selectedBreak=null;
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
 else if(!channelSelect.options.length)document.getElementById('status').textContent='Сначала укажите канал для публикации с помощью кнопки «Настроить каналы…».';
 updateModeUI();
 if(modeSelect.value.endsWith('_series'))autoPlaceBreaks();
}
function rememberEditorSelection(){
 const selection=window.getSelection();
 if(!selection||!selection.rangeCount)return;
 const range=selection.getRangeAt(0);
 if(range.commonAncestorContainer===editor||editor.contains(range.commonAncestorContainer))savedRange=range.cloneRange();
}
function restoreEditorSelection(){
 editor.focus();
 if(!savedRange)return false;
 const selection=window.getSelection();
 selection.removeAllRanges();
 selection.addRange(savedRange);
 return true;
}
function cleanClipboardHtml(markup){
 const parsed=new DOMParser().parseFromString(markup,'text/html');
 const sourceMatch=String(markup).match(/(?:SourceURL:|sourceurl\s*=\s*["'])(https?:\/\/[^\s"'<>]+)/i);
 let baseUrl=sourceMatch?sourceMatch[1]:null;
 const baseElement=parsed.querySelector('base[href]');
 if(baseElement&&/^https?:\/\//i.test(baseElement.href))baseUrl=baseElement.href;
 let removedImages=0;
 const publicUrl=value=>{
  const candidate=String(value||'').trim();
  if(!candidate||candidate.startsWith('data:')||candidate.startsWith('blob:'))return null;
  try{
   const resolved=new URL(candidate,baseUrl||undefined);
   return /^https?:$/.test(resolved.protocol)?resolved.href:null;
  }catch(_error){return null}
 };
 const srcsetUrl=value=>{
  if(!value)return null;
  for(const item of value.split(',')){
   const resolved=publicUrl(item.trim().split(/\s+/)[0]);
   if(resolved)return resolved;
  }
  return null;
 };
 for(const image of Array.from(parsed.querySelectorAll('img'))){
  const candidates=[
   image.getAttribute('src'),
   image.getAttribute('data-src'),
   image.getAttribute('data-original'),
   image.getAttribute('data-lazy-src'),
   srcsetUrl(image.getAttribute('srcset')),
   srcsetUrl(image.getAttribute('data-srcset'))
  ];
  let imageUrl=null;
  for(const candidate of candidates){
   imageUrl=publicUrl(candidate);
   if(imageUrl)break;
  }
  if(!imageUrl){image.remove();removedImages++;continue}
  image.setAttribute('src',imageUrl);
  for(const attribute of ['srcset','data-src','data-original','data-lazy-src','data-srcset','loading'])image.removeAttribute(attribute);
 }
 for(const video of Array.from(parsed.querySelectorAll('video'))){
  const url=publicUrl(video.getAttribute('src')||video.querySelector('source')?.getAttribute('src'));
  if(!url){video.remove();continue}
  video.setAttribute('src',url);
  video.querySelectorAll('source').forEach(source=>source.remove());
 }
 parsed.querySelectorAll('script,style,base,meta,link').forEach(node=>node.remove());
 return {html:parsed.body.innerHTML,removedImages};
}
function insertClipboardHtml(markup){
 const cleaned=cleanClipboardHtml(markup);
 restoreEditorSelection();
 document.execCommand('insertHTML',false,cleaned.html);
 rememberEditorSelection();
 updateSeriesStatus();
 if(cleaned.removedImages){
  document.getElementById('status').textContent=cleaned.removedImages===1
   ?'Вставка изображения из буфера пропущено: не удалось определить его публичный URL. Вставьте изображение по ссылке.'
   :'Вставка изображений из буфера пропущена: не удалось определить их публичные URL. Вставьте изображения по ссылкам.';
 }
}
function blobToDataUrl(blob){
 return new Promise((resolve,reject)=>{
  const reader=new FileReader();
  reader.onload=()=>resolve(String(reader.result||''));
  reader.onerror=()=>reject(reader.error||new Error('Не удалось прочитать изображение из буфера.'));
  reader.readAsDataURL(blob);
 });
}
function hideContextMenu(){contextMenu.hidden=true}
editor.addEventListener('mouseup',rememberEditorSelection);
editor.addEventListener('keyup',rememberEditorSelection);
editor.addEventListener('input',rememberEditorSelection);
editor.addEventListener('paste',event=>{
 const clipboard=event.clipboardData;
 if(!clipboard)return;
 const markup=clipboard.getData('text/html');
 if(markup){
  event.preventDefault();
  insertClipboardHtml(markup);
  return;
 }
});
document.addEventListener('selectionchange',rememberEditorSelection);
editor.addEventListener('click',event=>{
 const marker=event.target.closest('.series-break');
 if(marker&&isSeriesMode()){
  if(selectedBreak)selectedBreak.classList.remove('selected');
  selectedBreak=marker;
  marker.classList.add('selected');
 }else{
  if(selectedBreak)selectedBreak.classList.remove('selected');
  selectedBreak=null;
 }
});
editor.addEventListener('contextmenu',event=>{
 event.preventDefault();
 const marker=event.target.closest('.series-break');
 if(selectedBreak&&selectedBreak!==marker)selectedBreak.classList.remove('selected');
 selectedBreak=marker||null;
 if(selectedBreak)selectedBreak.classList.add('selected');
 else{
  const selection=window.getSelection();
  const hasSelection=selection&&selection.rangeCount&&!selection.getRangeAt(0).collapsed&&editor.contains(selection.anchorNode)&&editor.contains(selection.focusNode);
  if(hasSelection)rememberEditorSelection();
  else{
   let pointRange=null;
   if(document.caretRangeFromPoint)pointRange=document.caretRangeFromPoint(event.clientX,event.clientY);
   else if(document.caretPositionFromPoint){
    const position=document.caretPositionFromPoint(event.clientX,event.clientY);
    if(position){pointRange=document.createRange();pointRange.setStart(position.offsetNode,position.offset);pointRange.collapse(true)}
   }
   if(pointRange&&(pointRange.commonAncestorContainer===editor||editor.contains(pointRange.commonAncestorContainer)))savedRange=pointRange.cloneRange();
   else rememberEditorSelection();
  }
 }
 contextMenu.querySelector('[data-action="insert-break"]').hidden=!isSeriesMode();
 contextMenu.querySelector('[data-action="delete-break"]').hidden=!selectedBreak;
 contextMenu.hidden=false;
 const x=Math.min(event.clientX,window.innerWidth-contextMenu.offsetWidth-8);
 const y=Math.min(event.clientY,window.innerHeight-contextMenu.offsetHeight-8);
 contextMenu.style.left=Math.max(8,x)+'px';
 contextMenu.style.top=Math.max(8,y)+'px';
});
document.addEventListener('pointerdown',event=>{if(!contextMenu.contains(event.target))hideContextMenu()});
document.addEventListener('keydown',event=>{
 if(event.key==='Escape')hideContextMenu();
 if(selectedBreak&&(event.key==='Delete'||event.key==='Backspace')){
  event.preventDefault();
  selectedBreak.remove();
  selectedBreak=null;
  updateSeriesStatus();
 }
});
contextMenu.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',async()=>{
 const action=button.dataset.edit;
 hideContextMenu();
 restoreEditorSelection();
 if(action==='cut'||action==='copy'){
  document.execCommand(action,false,null);
  rememberEditorSelection();
  updateSeriesStatus();
  return;
 }
 try{
  if(navigator.clipboard&&navigator.clipboard.read){
   const items=await navigator.clipboard.read();
   for(const item of items){
    if(item.types.includes('text/html')){
     const blob=await item.getType('text/html');
     insertClipboardHtml(await blob.text());
     return;
    }
    const imageType=item.types.find(type=>type.startsWith('image/'));
    if(imageType){
     const blob=await item.getType(imageType);
     const dataUrl=await blobToDataUrl(blob);
     const safe=dataUrl.replace(/&/g,'&amp;').replace(/"/g,'&quot;');
     insertClipboardHtml('<img src="'+safe+'" alt="">');
     return;
    }
    if(item.types.includes('text/plain')){
     const blob=await item.getType('text/plain');
     restoreEditorSelection();
     document.execCommand('insertText',false,await blob.text());
     rememberEditorSelection();
     updateSeriesStatus();
     return;
    }
   }
  }
  const text=await navigator.clipboard.readText();
  restoreEditorSelection();
  document.execCommand('insertText',false,text);
  rememberEditorSelection();
  updateSeriesStatus();
 }catch(error){
  restoreEditorSelection();
  document.execCommand('paste',false,null);
  rememberEditorSelection();
  updateSeriesStatus();
 }
}));
contextMenu.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',()=>{
 const action=button.dataset.action;
 hideContextMenu();
 if(action==='insert-break')insertBreakAtSelection();
 if(action==='delete-break'&&selectedBreak){
  selectedBreak.remove();
  selectedBreak=null;
  updateSeriesStatus();
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
  status.textContent='Импорт завершён. Проверьте содержимое и при необходимости отредактируйте его.';
  editor.focus();
 }catch(error){status.textContent='Не удалось импортировать: '+(error&&error.message?error.message:String(error));}
}
document.getElementById('import-url').onclick=async()=>{
 const url=prompt('Вставьте ссылку на публикацию или страницу','https://');
 if(!url)return;
 const trimmedUrl=url.trim();
 if(!trimmedUrl.toLowerCase().startsWith('http://')&&!trimmedUrl.toLowerCase().startsWith('https://')){document.getElementById('status').textContent='Укажите полный URL, начинающийся с http:// или https://.';return;}
 await setImportedContent(window.pywebview.api.import_url(url.trim()));
};
document.getElementById('import-file').onclick=async()=>{
 const status=document.getElementById('status');
 try{
  const selected=await window.pywebview.api.open_file();
  if(!selected)return;
  if(selected.type==='draft'){
   applyDraft(selected.draft);
   status.textContent='Черновик загружен.';
  }else if(selected.type==='content'){
   await setImportedContent(Promise.resolve(selected.html));
  }else{
   throw new Error('Неизвестный формат файла.');
  }
 }catch(error){
  status.textContent='Не удалось открыть файл: '+(error&&error.message?error.message:String(error));
 }
};
function currentDraft(){
 return {
  format:'telegram-publisher-draft',
  version:1,
  html:editor.innerHTML,
  mode:modeSelect.value,
  series:isSeriesMode(),
  profile_id:channelSelect.value||null
 };
}
function draftFilename(){
 const heading=editor.querySelector('h1,h2,h3,h4,h5,h6');
 let title=heading?(heading.innerText||heading.textContent||'').trim():'';
 if(!title){
  const clone=editor.cloneNode(true);
  clone.querySelectorAll('.series-break').forEach(node=>node.remove());
  const text=(clone.innerText||clone.textContent||'').replace(/\s+/g,' ').trim();
  title=text.split(' ').filter(Boolean).slice(0,3).join(' ');
 }
 title=title.replace(/[<>:"/\\|?*\x00-\x1f]/g,' ').replace(/\s+/g,' ').trim().replace(/[. ]+$/,'');
 return (title||'Черновик').slice(0,100);
}
function applyDraft(draft){
 if(!draft||draft.format!=='telegram-publisher-draft'||draft.version!==1||
    typeof draft.html!=='string'||
    !['rich','plain','rich_series','plain_series'].includes(draft.mode)||
    typeof draft.series!=='boolean'){
  throw new Error('Файл не является поддерживаемым черновиком Telegram Publisher.');
 }
 editor.innerHTML=draft.html;
 modeSelect.value=draft.mode;
 seriesCheckbox.checked=draft.series;
 channelSelect.value=draft.profile_id||'';
 updateModeUI();
 editor.focus();
}
document.getElementById('save-draft').onclick=async()=>{
 const status=document.getElementById('status');
 try{
  const saved=await window.pywebview.api.save_draft(currentDraft(),draftFilename());
  if(saved)status.textContent='Черновик сохранён: '+saved;
 }catch(error){
  status.textContent='Не удалось сохранить черновик: '+(error&&error.message?error.message:String(error));
 }
};
document.getElementById('manual').onclick=async()=>{
 try{await window.pywebview.api.open_manual()}
 catch(error){document.getElementById('status').textContent='Не удалось открыть руководство: '+(error&&error.message?error.message:String(error));}
};
document.querySelectorAll('[data-cmd]').forEach(button=>button.addEventListener('click',()=>{
 editor.focus();const cmd=button.dataset.cmd;document.execCommand(cmd,false,button.dataset.value||null);
}));
function askUrl(label){const value=prompt(label,'https://');return value&&/^https?:\/\//i.test(value)?value.trim():null}
document.getElementById('link').onclick=()=>{const url=askUrl('Публичный URL ссылки');if(url){editor.focus();document.execCommand('createLink',false,url)}};
function currentPartMediaCount(){
 if(!isSeriesMode())return partMediaCount(Array.from(editor.childNodes).filter(node=>!(node.nodeType===1&&node.classList.contains('series-break'))));
 const selection=window.getSelection();
 let selected=selection&&selection.anchorNode;
 while(selected&&selected.parentNode!==editor)selected=selected.parentNode;
 const rawParts=[[]];
 let selectedIndex=0;
 for(const node of Array.from(editor.childNodes)){
  if(node.nodeType===1&&node.classList.contains('series-break')){rawParts.push([]);continue}
  rawParts[rawParts.length-1].push(node);
  if(selected&&(node===selected||node.contains&&node.contains(selected)))selectedIndex=rawParts.length-1;
 }
 return partMediaCount(rawParts[selectedIndex]||[]);
}
function insertMediaFromUrl(){
 if(!isRichMode()&&currentPartMediaCount()>=1){document.getElementById('status').textContent='В одном обычном сообщении допускается только одно изображение или видео.';return}
 const url=askUrl('Публичный URL изображения или видео');
 if(!url)return;
 let parsed;
 try{parsed=new URL(url)}catch(error){document.getElementById('status').textContent='Не удалось разобрать адрес.';return}
 const host=parsed.hostname.toLowerCase().replace(/^www\./,'');
 const isVideoSite=host==='youtube.com'||host.endsWith('.youtube.com')||host==='youtu.be'||host==='youtube-nocookie.com'||host.endsWith('.youtube-nocookie.com');
 if(isVideoSite){
  const safe=url.replace(/&/g,'&amp;').replace(/"/g,'&quot;');
  editor.focus();
  document.execCommand('insertHTML',false,'<p><a href="'+safe+'" data-publication-media-preview="video">'+safe+'</a></p>');
  document.getElementById('status').textContent=isRichMode()
   ?'Это страница сайта видеохостинга, а не адрес видеофайла. Такой способ импорта годится для публикации в виде обычного сообщения, но не рич-сообщения. Для встраивания видео в рич-сообщение укажите прямой URL файла.'
   :'При публикации ссылка на видеосайт будет скрыта, а её URL передан Telegram для предпросмотра.';
  updateSeriesStatus();
  return;
 }
 const path=parsed.pathname+parsed.search+parsed.hash;
 const videoByExtension=/\.(mp4|m4v|mov|webm|mkv)(?:$|[?#])/i.test(path);
 const imageByExtension=/\.(png|jpe?g|gif|webp|avif|bmp)(?:$|[?#])/i.test(path);
 const kind=videoByExtension?'video':imageByExtension?'image':(confirm('Это прямой URL видеофайла?\nНажмите «ОК» для видео или «Отмена» для изображения.')?'video':'image');
 editor.focus();
 const safe=url.replace(/&/g,'&amp;').replace(/"/g,'&quot;');
 const markup=kind==='image'?'<p><img src="'+safe+'" alt=""></p>':'<p><video controls src="'+safe+'"></video></p>';
 document.execCommand('insertHTML',false,markup);
 updatePlainCompatibility();
 updateSeriesStatus();
}
document.getElementById('media').onclick=insertMediaFromUrl;
document.getElementById('table').onclick=()=>{const rows=Math.max(1,Math.min(20,Number(prompt('Количество строк','2'))||2));const cols=Math.max(1,Math.min(10,Number(prompt('Количество столбцов','2'))||2));let table='<table><tbody>';for(let r=0;r<rows;r++){table+='<tr>';for(let c=0;c<cols;c++)table+='<td><br></td>';table+='</tr>'}table+='</tbody></table><p><br></p>';editor.focus();document.execCommand('insertHTML',false,table)};
const seriesStatus=document.getElementById('series-status');
function isSeriesMode(){return modeSelect.value.endsWith('_series')||seriesCheckbox.checked}
function isRichMode(){return modeSelect.value==='rich'||modeSelect.value==='rich_series'||modeSelect.value==='media_text'}
function messageLimit(){return isRichMode()?32768:4096}
function makeBreak(){
 const marker=document.createElement('div');
 marker.className='series-break';
 marker.contentEditable='false';
 marker.draggable=false;
 marker.dataset.postBreak='1';
 marker.textContent='Разрыв сообщения — нажмите Del, чтобы удалить';
 return marker;
}
function partNodes(){
 const parts=[[]];
 for(const node of Array.from(editor.childNodes)){
  if(node.nodeType===1&&node.classList.contains('series-break')){parts.push([]);continue}
  parts[parts.length-1].push(node);
 }
 return parts.filter(nodes=>{
  const wrapper=document.createElement('div');
  for(const node of nodes)wrapper.appendChild(node.cloneNode(true));
  return Boolean((wrapper.innerText||wrapper.textContent||'').trim()||wrapper.querySelector('img,video'));
 });
}
function htmlParts(){
 return partNodes().map(nodes=>{
  const wrapper=document.createElement('div');
  for(const node of nodes)wrapper.appendChild(node.cloneNode(true));
  return wrapper.innerHTML.trim();
 }).filter(part=>part.length>0);
}
function partLength(nodes){
 const wrapper=document.createElement('div');
 for(const node of nodes)wrapper.appendChild(node.cloneNode(true));
 wrapper.querySelectorAll('.series-break').forEach(node=>node.remove());
 return (wrapper.innerText||wrapper.textContent||'').trim().length;
}
function partMediaCount(nodes){
 const wrapper=document.createElement('div');
 for(const node of nodes)wrapper.appendChild(node.cloneNode(true));
 return wrapper.querySelectorAll('img,video').length;
}
function updateSeriesStatus(){
 const series=isSeriesMode();
 const parts=series?partNodes():[Array.from(editor.childNodes).filter(node=>!(node.nodeType===1&&node.classList.contains('series-break')))];
 const limit=messageLimit();
 const enforceSingleMedia=!isRichMode();
 const lengths=parts.map(partLength);
 const mediaCounts=parts.map(partMediaCount);
 const hasContent=parts.some((part,index)=>lengths[index]>0||mediaCounts[index]>0);
 seriesStatus.hidden=!hasContent;
 const overflow=lengths.some(length=>length>limit);
 const tooMuchMedia=enforceSingleMedia&&mediaCounts.some(count=>count>1);
 seriesStatus.classList.toggle('warning',overflow||tooMuchMedia);
 if(!hasContent){seriesStatus.textContent='';return true}
 seriesStatus.textContent=parts.map((part,index)=>{
  const prefix=series?'Пост '+(index+1):'Сообщение';
  const notes=[];
  if(lengths[index]>limit)notes.push('превышен лимит, перенесите часть текста');
  else if(lengths[index]===limit)notes.push('лимит заполнен, больше не стоит сюда ничего добавлять');
  if(enforceSingleMedia&&mediaCounts[index]>1)notes.push('допускается не более одного изображения или видео на пост');
  return prefix+': '+lengths[index]+'/'+limit+' символов'+(mediaCounts[index]?' · медиа: '+mediaCounts[index]:'')+(notes.length?' — '+notes.join('; ')+'.':'');
 }).join('\n');
 return !overflow&&!tooMuchMedia;
}
const PLAIN_SUBSTITUTIONS=[
 {selector:'h1,h2,h3,h4,h5,h6',message:'Уровень заголовка будет заменён жирным текстом.'},
 {selector:'table',message:'Таблица будет преобразована в текстовые строки.'},
 {selector:'img,video',message:'Медиа будет заменено скрытой ссылкой для предпросмотра.'},
 {selector:'mark,sub,sup,small,big,font,span[style]',message:'Это оформление не поддерживается в обычном режиме; текст сохранится.'}
];
function updatePlainCompatibility(){
 editor.querySelectorAll('.plain-unsupported').forEach(node=>{
  node.classList.remove('plain-unsupported');
  if(node.dataset.plainOriginalTitle!==undefined){
   if(node.dataset.plainOriginalTitle)node.title=node.dataset.plainOriginalTitle;
   else node.removeAttribute('title');
   delete node.dataset.plainOriginalTitle;
  }
 });
 if(isRichMode())return;
 for(const rule of PLAIN_SUBSTITUTIONS){
  editor.querySelectorAll(rule.selector).forEach(node=>{
   node.classList.add('plain-unsupported');
   node.dataset.plainOriginalTitle=node.getAttribute('title')||'';
   node.title=rule.message;
  });
 }
}
function updateModeUI(){
 const rich=isRichMode();
 document.querySelectorAll('[data-rich-only]').forEach(button=>button.hidden=!rich);
 document.getElementById('series-tools').classList.toggle('visible',isSeriesMode());
 seriesCheckbox.checked=modeSelect.value.endsWith('_series');
 updatePlainCompatibility();
 updateSeriesStatus();
}
function preferredSplitBoundary(text,start,end,limit){
 const segment=text.slice(start,end);
 const sentencePattern=/[.!?…]+(?:["'»”’)}\]]*)\s+/g;
 let match,lastSentenceBoundary=0;
 while((match=sentencePattern.exec(segment))!==null){
  const boundary=start+match.index+match[0].trimEnd().length;
  if(boundary>start+Math.floor(limit*0.5))lastSentenceBoundary=boundary;
 }
 if(lastSentenceBoundary>start)return lastSentenceBoundary;
 const newline=text.lastIndexOf('\n',end);
 const space=text.lastIndexOf(' ',end);
 const boundary=Math.max(newline,space);
 return boundary>start+Math.floor(limit*0.5)?boundary:end;
}
function splitOversizedList(node,limit){
 const items=Array.from(node.children).filter(item=>item.tagName==='LI');
 if(!items.length)return [node];
 const chunks=[];
 let current=node.cloneNode(false),used=0;
 const flush=()=>{
  if(current.children.length)chunks.push(current);
  current=node.cloneNode(false);
  used=0;
 };
 for(const item of items){
  const itemLength=(item.innerText||item.textContent||'').trim().length;
  const pieces=itemLength>limit?splitOversizedNode(item,limit):[item];
  for(const piece of pieces){
   const length=(piece.innerText||piece.textContent||'').trim().length;
   const separator=current.children.length?1:0;
   if(current.children.length&&used+separator+length>limit)flush();
   const nextSeparator=current.children.length?1:0;
   current.appendChild(piece.cloneNode(true));
   used+=nextSeparator+length;
  }
 }
 flush();
 return chunks.length?chunks:[node];
}
function splitOversizedNode(node,limit){
 const originalText=node.textContent||'';
 if(node.nodeType===Node.ELEMENT_NODE&&['UL','OL'].includes(node.tagName)&&(node.innerText||originalText).trim().length>limit){
  return splitOversizedList(node,limit);
 }
 if(originalText.length<=limit)return [node];
 if(node.nodeType===Node.TEXT_NODE){
  const chunks=[];
  let start=0;
  while(start<originalText.length){
   let end=Math.min(start+limit,originalText.length);
   if(end<originalText.length){
    const boundary=preferredSplitBoundary(originalText,start,end,limit);
    if(boundary>start&&boundary<end)end=boundary;
   }
   if(end<=start)end=Math.min(start+limit,originalText.length);
   const value=originalText.slice(start,end).trim();
   if(value)chunks.push(document.createTextNode(value));
   start=end;
   while(start<originalText.length&&/\s/.test(originalText[start]))start++;
  }
  return chunks.length?chunks:[node];
 }
 const working=node.cloneNode(true);
 const media=Array.from(working.querySelectorAll('img,video'));
 media.forEach(item=>item.remove());
 const walker=document.createTreeWalker(working,NodeFilter.SHOW_TEXT);
 const textNodes=[];
 while(walker.nextNode())textNodes.push(walker.currentNode);
 const combined=textNodes.map(item=>item.nodeValue||'').join('');
 if(combined.length<=limit)return [node];
 const chunks=[];
 let start=0;
 while(start<combined.length){
  let end=Math.min(start+limit,combined.length);
  if(end<combined.length){
   const boundary=preferredSplitBoundary(combined,start,end,limit);
   if(boundary>start&&boundary<end)end=boundary;
  }
  if(end<=start)end=Math.min(start+limit,combined.length);
  let cursor=0,first=null,last=null,firstOffset=0,lastOffset=0;
  for(const textNode of textNodes){
   const size=(textNode.nodeValue||'').length;
   if(first===null&&start<cursor+size){first=textNode;firstOffset=start-cursor}
   if(end<=cursor+size){last=textNode;lastOffset=end-cursor;break}
   cursor+=size;
  }
  if(first&&last){
   const range=document.createRange();
   range.setStart(first,firstOffset);
   range.setEnd(last,lastOffset);
   const fragment=range.cloneContents();
   const clone=working.cloneNode(false);
   clone.appendChild(fragment);
   if((clone.textContent||'').trim())chunks.push(clone);
  }
  start=end;
  while(start<combined.length&&/\s/.test(combined[start]))start++;
 }
 if(!chunks.length)return [node];
 media.forEach(item=>chunks[0].appendChild(item.cloneNode(true)));
 return chunks;
}
function autoPlaceBreaks(){
 editor.querySelectorAll('.series-break').forEach(node=>node.remove());
 const limit=messageLimit();
 const originals=Array.from(editor.childNodes);
 const output=[];
 let used=0,hasContent=false;
 for(const node of originals){
  const text=(node.innerText||node.textContent||'').trim();
  const mediaCount=node.nodeType===1?node.querySelectorAll('img,video').length:0;
  if(!text&&!mediaCount){if(output.length)output.push(node);continue}
  const chunks=splitOversizedNode(node,limit);
  for(let index=0;index<chunks.length;index++){
   const chunk=chunks[index];
   const length=(chunk.innerText||chunk.textContent||'').trim().length;
   const chunkMedia=chunk.nodeType===1?chunk.querySelectorAll('img,video').length:0;
   if(hasContent&&used+length>limit){output.push(makeBreak());used=0;hasContent=false}
   output.push(chunk);
   used+=length;
   if(length||chunkMedia)hasContent=true;
   if(index<chunks.length-1){output.push(makeBreak());used=0;hasContent=false}
  }
 }
 editor.replaceChildren(...output);
 updateSeriesStatus();
}
function insertBreakAtSelection(){
 if(!isSeriesMode())return;
 let range=savedRange?savedRange.cloneRange():null;
 const selection=window.getSelection();
 if(!range&&selection&&selection.rangeCount)range=selection.getRangeAt(0).cloneRange();
 if(range&&!(range.commonAncestorContainer===editor||editor.contains(range.commonAncestorContainer)))range=null;
 const marker=makeBreak();
 if(!range||!editor.lastChild){
  editor.appendChild(marker);
 }else{
  range.collapse(false);
  let root=range.startContainer;
  while(root&&root!==editor&&root.parentNode!==editor)root=root.parentNode;
  if(root===editor)root=null;
  try{
   const tail=document.createRange();
   if(root){
    tail.setStart(range.startContainer,range.startOffset);
    tail.setEndAfter(editor.lastChild);
    const remainder=tail.extractContents();
    editor.insertBefore(marker,root.nextSibling);
    if(remainder.childNodes.length)editor.insertBefore(remainder,marker.nextSibling);
   }else{
    const offset=range.startOffset;
    tail.setStart(editor,offset);
    tail.setEnd(editor,editor.childNodes.length);
    const remainder=tail.extractContents();
    editor.appendChild(marker);
    if(remainder.childNodes.length)editor.insertBefore(remainder,marker.nextSibling);
   }
  }catch(error){
   editor.appendChild(marker);
  }
 }
 if(selectedBreak)selectedBreak.classList.remove('selected');
 selectedBreak=null;
 updateSeriesStatus();
}
document.getElementById('insert-break').addEventListener('click',insertBreakAtSelection);
editor.addEventListener('input',()=>{updatePlainCompatibility();updateSeriesStatus()});
modeSelect.addEventListener('change',()=>{
 seriesCheckbox.checked=modeSelect.value.endsWith('_series');
 if(modeSelect.value.endsWith('_series'))autoPlaceBreaks();
 else editor.querySelectorAll('.series-break').forEach(node=>node.remove());
 updateModeUI();
});
seriesCheckbox.addEventListener('change',()=>{
 if(seriesCheckbox.checked&&modeSelect.value==='plain')modeSelect.value='plain_series';
 if(seriesCheckbox.checked&&modeSelect.value==='rich')modeSelect.value='rich_series';
 if(!seriesCheckbox.checked&&modeSelect.value.endsWith('_series'))modeSelect.value=modeSelect.value==='plain_series'?'plain':'rich';
 if(seriesCheckbox.checked&&modeSelect.value.endsWith('_series'))autoPlaceBreaks();
 else editor.querySelectorAll('.series-break').forEach(node=>node.remove());
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
  document.getElementById('status').textContent='Выберите канал (кнопка "Настроить каналы")';
  return;
 }
 const text=editor.innerText.trim();
 if(!text&&!editor.querySelector('img,video')){
  document.getElementById('status').textContent='Добавьте текст, изображение или видео перед публикацией.';
  return;
 }
 if(!updateSeriesStatus()){
  document.getElementById('status').textContent='Исправьте превышение лимита или оставьте не более одного медиа на пост перед публикацией.';
  return;
 }
 const usesSendMessage=modeSelect.value==='plain'||modeSelect.value==='plain_series';
 if(!usesSendMessage&&!confirm('Опубликовать пост в выбранном канале?'))return;
 const publishButton=document.getElementById('publish');
 publishButton.disabled=true;
 document.getElementById('status').textContent=usesSendMessage?'Отправка: ожидается финальная правка…':'Подготовка публикации…';
 try{await window.pywebview.api.publish(currentResult(usesSendMessage?'review_publish':'publish'));}
 catch(error){
  publishButton.disabled=false;
  document.getElementById('status').textContent='Не удалось начать публикацию: '+(error&&error.message?error.message:String(error));
 }
};
document.getElementById('manage').onclick=async()=>{await window.pywebview.api.finish(currentResult('manage_profiles'))};
let statusPolling=false;
async function pollEditorStatus(){
 if(statusPolling||!window.pywebview||!window.pywebview.api)return;
 statusPolling=true;
 try{
  const update=await window.pywebview.api.get_status();
  if(update){
   if(update.clear){editor.innerHTML='';updateSeriesStatus()}
   if(Array.isArray(update.profiles)){
    config.profiles=update.profiles;
    channelSelect.replaceChildren();
    for(const profile of update.profiles){
     const option=document.createElement('option');
     option.value=profile.profile_id;
     option.textContent=profile.name+' — '+profile.chat_id;
     channelSelect.append(option);
    }
    channelSelect.value=update.selected_profile_id||'';
    if(!channelSelect.value&&channelSelect.options.length)channelSelect.selectedIndex=0;
   }
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


MANUAL_HTML = r"""<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Руководство — Telegram Publisher</title>
<style>body{font:16px "Segoe UI",sans-serif;line-height:1.55;color:#222;background:#f4f5f7;margin:0;padding:24px}article{max-width:760px;margin:0 auto;background:#fff;padding:28px 34px;border-radius:8px;box-shadow:0 1px 5px #0001}h1{margin-top:0}h2{margin-top:1.5em;font-size:1.2em}a{color:#1558a6}li{margin:.35em 0}.meta{color:#555}</style>
</head><body><article>
<h1>Руководство по Telegram Publisher</h1>
<p class="meta"><b>Версия:</b> 1.0.0<br><b>Дата сборки:</b> 25.10.2026<br><b>Автор:</b> Анкап-тян</p>
<p>Сайт: <a href="https://ancapchan.info" target="_blank" rel="noreferrer">https://ancapchan.info</a><br>Телеграм-канал: <a href="https://t.me/ancapchan" target="_blank" rel="noreferrer">https://t.me/ancapchan</a><br><p>Донаты: <a href="https://ancapchan.info/donate" target="_blank" rel="noreferrer">https://ancapchan.info/donate</a></p>
<h2>Задача приложения</h2>
<p>Telegram Publisher — это инструмент для подготовки и публикации сообщений в Telegram-каналах. Можно настроить несколько телеграм-каналов и выбирать, каие посты куда публиковать. Доступны различные режимы публикации (обычные сообщения и рич-сообщения) и разбивка текста на серию постов.</p>
<h2>Импорт и черновики</h2>
<p>Пост можно создавать непосредственно в редакторе, вставить из буфера обмена, загрузить из файла или импортировать с веб-страницы по URL. Поддерживаются форматы TXT, HTML, Markdown, DOCX и ODT. Черновик поста можно сохранить в файле .draft, а позже загрузить для дальнейшего редактирования</p>
<ul><li><b>Импортировать по ссылке</b> — загрузить публикацию со страницы по URL.</li><li><b>Открыть файл</b> — импортировать TXT, HTML, Markdown, DOCX или ODT либо восстановить черновик .draft.</li><li><b>Сохранить черновик</b> — сохранить форматирование, режим публикации, выбранный канал и положение разрывов для серии постов в файле .draft.</li></ul>
<h2>Подготовка публикации</h2>
<p>Основная область окна — визуальный редактор. Панель инструментов позволяет применять форматирование, создавать списки, заголовки, цитаты, ссылки и таблицы. Кнопка «Медиа по URL» добавляет изображение или видео по публичной ссылке. В зависимости от выбранного способа публикации доступны разные инструменты редактирования. Если выбранный способ публикации не позволяет сохранить используемое форматирование, будут использоваться альтернативные варианты форматирования.</p>
<h2>Выбор способа публикации</h2>
<p>Обычные сообщения имеют минимальное форматирование: жирный шрифт, курсив, подчёркивание, зачёркивание, гиперссылки, цитаты. Можно вставить одну картинку или видео, для этого пользуется скрытая ссылка, которую телеграм преобразует в превью. Предельный размер такого сообщения - 4096 символов.</p>
<p>Рич-сообщения позволяют более сложное форматирование. Для длинных публикаций можно выбрать серию сообщений.</p>
<p>В режиме серии кнопка «Разрыв сообщения» вставляет границу в текущем месте. Разрыв можно выбрать и удалить. Проверяй предупреждения о длине и количестве медиа перед публикацией.</p>
<h2>Настройка каналов</h2>
<p>В нижней части окна по кнопке «Настроить каналы...» можно добавить один или несколько профилей каналов, указав произвольное имя профиля, идентификатор канала и токен бота, имеющего административные полномочия в канале - публикация будет осуществляться через этого бота.</p>
<h2>Публикация</h2>
<p>По нажатию кнопки «Опубликовать» в режиме публикации обычных сообщений предлагается предпросмотр, где приложение показывает, какой именно текст будет передан в телеграм. В это время можно внести финальные правки, и лишь затем подтвердить или отменить публикацию. Для рич-сообщений предпросмотра не происходит. Статус внизу окна показывает ход работы и результат.</p>
</article></body></html>"""

class EditorApi:
    """Передать результат редактора вызывающему приложению."""

    def __init__(self, output_path: Path, status_path: Path, window: object) -> None:
        self.output_path = output_path
        self.status_path = status_path
        self.window = window
        self.manual_window = None

    def finish(self, result: dict) -> None:
        """Передать запрос приложению; настройки не закрывают редактор."""
        self.output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

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

    def open_file(self) -> dict | None:
        """Открыть документ для импорта или восстановить черновик редактора."""
        paths = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "Поддерживаемые форматы (*.draft;*.txt;*.html;*.htm;*.md;*.markdown;*.docx;*.odt)",
                "Черновик Telegram Publisher (*.draft)",
                "Текстовые файлы (*.txt)",
                "HTML (*.html;*.htm)",
                "Markdown (*.md;*.markdown)",
                "Документы Word (*.docx)",
                "Документы OpenDocument (*.odt)",
            ),
        )
        if not paths:
            return None
        path = Path(paths[0])
        if path.suffix.lower() == ".draft":
            try:
                draft = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError(f"Не удалось прочитать файл черновика: {error}") from error
            return {"type": "draft", "draft": draft}
        return {"type": "content", "html": import_from_file(path)}

    def open_manual(self) -> None:
        """Открыть отдельное окно руководства, не закрывая редактор."""
        if self.manual_window is not None:
            try:
                self.manual_window.show()
                self.manual_window.restore()
                return
            except Exception:
                self.manual_window = None
        manual = webview.create_window(
            "Руководство — Telegram Publisher", html=MANUAL_HTML,
            width=780, height=780, resizable=True,
        )
        self.manual_window = manual
        manual.events.closed += lambda *_args: setattr(self, "manual_window", None)

    def save_draft(self, draft: dict, filename: str = "Черновик") -> str | None:
        """Сохранить полное состояние редактора в файл .draft."""
        if not isinstance(draft, dict):
            raise ValueError("Не удалось получить данные черновика.")
        if (
            draft.get("format") != "telegram-publisher-draft"
            or draft.get("version") != 1
            or not isinstance(draft.get("html"), str)
            or draft.get("mode") not in {"rich", "plain", "rich_series", "plain_series"}
            or not isinstance(draft.get("series"), bool)
            or (draft.get("profile_id") is not None and not isinstance(draft.get("profile_id"), str))
        ):
            raise ValueError("Редактор передал некорректные данные черновика.")
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(filename))
        safe_name = re.sub(r"\s+", " ", safe_name).strip(" .")[:100] or "Черновик"
        path = self.window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=f"{safe_name}.draft",
            file_types=("Черновики Telegram Publisher (*.draft)",),
        )
        if not path:
            return None
        if isinstance(path, (list, tuple)):
            path = path[0] if path else None
        if not path:
            return None
        destination = Path(path)
        if destination.suffix.lower() != ".draft":
            destination = destination.with_suffix(".draft")
        destination.write_text(
            json.dumps(draft, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(destination)

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
    window.expose(api.finish, api.publish, api.get_status, api.import_url, api.import_file, api.open_file, api.save_draft, api.open_manual)

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
