import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, MouseEvent, WheelEvent } from 'react'
type Frame = { running: boolean; image?: string; url?: string; title?: string; width?: number; height?: number; tabs?: { index: number; title: string; url: string }[] }
export default function BrowserDock() {
 const [expanded,setExpanded]=useState(true),[takeover,setTakeover]=useState(false),[frame,setFrame]=useState<Frame>({running:false}),[address,setAddress]=useState(''),[busy,setBusy]=useState(false)
 const imageRef=useRef<HTMLImageElement>(null)
 const refresh=useCallback(async()=>{try{const r=await fetch('/api/browser/frame',{cache:'no-store'});if(r.ok){const n=await r.json() as Frame;setFrame(n);if(n.url)setAddress(n.url)}}catch{}},[])
 useEffect(()=>{if(!expanded)return;void refresh();const t=window.setInterval(()=>void refresh(),takeover?650:1100);return()=>window.clearInterval(t)},[expanded,takeover,refresh])
 const act=useCallback(async(p:Record<string,unknown>)=>{setBusy(true);try{const r=await fetch('/api/browser/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});if(!r.ok){const d=await r.json().catch(()=>({}));throw new Error(d.error||'Browser action failed')}await refresh()}catch(e){console.error(e)}finally{setBusy(false)}},[refresh])
 const navigate=()=>{if(address.trim())void act({action:'navigate',url:address.trim()})}
 const key=(e:KeyboardEvent<HTMLDivElement>)=>{if(!takeover||e.ctrlKey||e.metaKey||e.altKey)return;if(e.key.length===1||['Enter','Tab','Escape','Backspace','Delete','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home','End','PageUp','PageDown'].includes(e.key)){e.preventDefault();void act({action:'key',key:e.key})}}
 const click=(e:MouseEvent<HTMLImageElement>)=>{if(!takeover||!imageRef.current)return;const r=imageRef.current.getBoundingClientRect();void act({action:'click',x:(e.clientX-r.left)*(frame.width||1440)/r.width,y:(e.clientY-r.top)*(frame.height||1000)/r.height})}
 const wheel=(e:WheelEvent<HTMLDivElement>)=>{if(takeover){e.preventDefault();void act({action:'scroll',dx:e.deltaX,dy:e.deltaY})}}
 return <section className="browser-dock">
  <div className="browser-dock-bar"><button className="browser-dock-title" onClick={()=>setExpanded(v=>!v)} aria-expanded={expanded}><span className={frame.running?'browser-live-dot active':'browser-live-dot'}/><strong>Live Browser</strong><span className="browser-dock-subtitle">{frame.running?(frame.title||'Chromium running'):'Waiting for Thursday to open a page'}</span><span>{expanded?'▾':'▸'}</span></button>
  {expanded&&<div className="browser-dock-actions"><button className={takeover?'browser-takeover active':'browser-takeover'} onClick={()=>setTakeover(v=>!v)}>{takeover?'You control':'Take control'}</button><button onClick={()=>void refresh()}>↻</button></div>}</div>
  {expanded&&<div className="browser-dock-body"><div className="browser-address"><button onClick={()=>void act({action:'back'})} disabled={!frame.running}>←</button><button onClick={()=>void act({action:'forward'})} disabled={!frame.running}>→</button><button onClick={()=>void act({action:'reload'})} disabled={!frame.running}>↻</button><input value={address} onChange={e=>setAddress(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')navigate()}} placeholder="https://www.youtube.com"/><button onClick={navigate} disabled={busy}>Go</button></div>
  {frame.running&&frame.image?<div className={takeover?'browser-screen interactive':'browser-screen'} tabIndex={takeover?0:-1} onKeyDown={key} onWheel={wheel}><img ref={imageRef} src={'data:image/png;base64,'+frame.image} onClick={click} draggable={false} alt="Live Chromium browser view"/>{takeover&&<span className="browser-control-hint">Takeover active · click page, then type</span>}</div>:<div className="browser-empty"><span>◉</span><strong>Your browser will appear here</strong><p>Ask Thursday to open a website. The live view appears automatically.</p></div>}
  <div className="browser-dock-footer"><span>{frame.url||'No active page'}</span><span>{takeover?'Manual control enabled':'Thursday controls browser'}</span></div>
  {!!frame.tabs?.length&&<div className="browser-tabs">{frame.tabs.map(t=><span key={t.index}>{t.title||'New tab'}</span>)}</div>}</div>}
 </section>
}
