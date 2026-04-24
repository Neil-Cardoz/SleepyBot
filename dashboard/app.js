/* SleepSense AI — Dashboard JS */

const WS_URL  = `ws://${location.host}/ws`;
const API     = `http://${location.host}`;
const MAX_PTS = 150;

const STAGES = {
    "P":  {name:"Pre-Sleep",     desc:"Body preparing for sleep",           color:"#6366f1"},
    "W":  {name:"Awake",         desc:"Conscious wakefulness detected",      color:"#f59e0b"},
    "N1": {name:"Light Sleep",   desc:"NREM Stage 1 — drifting off",         color:"#22d3ee"},
    "N2": {name:"Moderate Sleep",desc:"NREM Stage 2 — sleep spindles",       color:"#3b82f6"},
    "N3": {name:"Deep Sleep",    desc:"NREM Stage 3 — slow-wave restorative",color:"#8b5cf6"},
    "R":  {name:"REM Sleep",     desc:"Rapid eye movement — dreaming",       color:"#ef4444"},
    "---":{name:"Waiting...",    desc:"Collecting data for first prediction", color:"#64748b"},
};

let ws, autoTmr, predCount=0, stageCnt={P:0,W:0,N1:0,N2:0,N3:0,R:0};
let chartHR, chartHypno;

// ── Init ────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", ()=>{
    initCharts();
    connectWS();
    setInterval(tick, 1000);
    setInterval(pollStatus, 5000);
});

// ── WebSocket ───────────────────────────────────────────────────────────────
function connectWS(){
    ws = new WebSocket(WS_URL);
    ws.onopen  = ()=> setDot("ws",true);
    ws.onclose = ()=>{ setDot("ws",false); setTimeout(connectWS, 3000); };
    ws.onerror = ()=> setDot("ws",false);
    ws.onmessage = e=>{
        try{
            const d = JSON.parse(e.data);
            if(d.type==="pong") return;
            onData(d);
        }catch(x){}
    };
}

// ── Handle data ─────────────────────────────────────────────────────────────
function onData(d){
    predCount++;

    // BPM ring
    const bpm = Math.round(d.hr);
    const bpmEl = document.getElementById("bpm-val");
    bpmEl.textContent = bpm || "--";
    if(bpm > 100)      { bpmEl.style.color="#ef4444"; bpmEl.style.textShadow="0 0 28px rgba(239,68,68,.3)"; }
    else if(bpm > 0)   { bpmEl.style.color="#10b981"; bpmEl.style.textShadow="0 0 28px rgba(16,185,129,.3)"; }
    else               { bpmEl.style.color="#64748b"; bpmEl.style.textShadow="none"; }

    // Ring arc: map 40-200 bpm to 0-100%
    const pct = Math.max(0, Math.min(1, (bpm-40)/160));
    const circ = 339.29;
    document.getElementById("ring-fg").style.strokeDashoffset = circ * (1-pct);
    document.getElementById("ring-fg").style.stroke = bpm>100?"#ef4444":bpm>0?"#10b981":"#64748b";
    document.getElementById("bpm-sub").textContent = bpm>0 ? `${bpm} BPM detected` : "No pulse detected";

    // Stage
    const s = d.stage || "---";
    const meta = STAGES[s] || STAGES["---"];
    const badge = document.getElementById("stage-badge");
    badge.textContent = s;
    badge.style.borderColor = meta.color;
    badge.style.color = meta.color;
    badge.style.background = meta.color+"18";
    badge.classList.toggle("active", s!=="---");
    document.getElementById("stage-title").textContent = meta.name;
    document.getElementById("stage-desc").textContent  = meta.desc;
    document.getElementById("conf-bar").style.width = (d.conf*100)+"%";
    document.getElementById("conf-text").textContent = (d.conf*100).toFixed(1)+"% confidence";

    // Accel
    document.getElementById("val-x").textContent = d.acc_x;
    document.getElementById("val-y").textContent = d.acc_y;
    document.getElementById("val-z").textContent = d.acc_z;
    setBar("bar-x", d.acc_x);
    setBar("bar-y", d.acc_y);
    setBar("bar-z", d.acc_z);

    // Charts
    const t = new Date(d.ts).toLocaleTimeString("en-GB",{hour12:false,hour:"2-digit",minute:"2-digit",second:"2-digit"});
    pushChart(chartHR, t, d.hr);
    const stageY = {P:0,W:1,N1:2,N2:3,N3:4,R:5};
    if(s in stageY) pushChart(chartHypno, t, stageY[s]);

    // Distribution
    if(s && s!=="---"){ stageCnt[s]=(stageCnt[s]||0)+1; updateDist(); }

    // Stats
    document.getElementById("sv-samples").textContent = d.n || 0;
    document.getElementById("sv-pred").textContent = predCount;
}

// ── Accel bar ───────────────────────────────────────────────────────────────
function setBar(id, v){
    const bar = document.getElementById(id);
    const pct = (v/128)*50;
    if(pct>=0){ bar.style.left="50%"; bar.style.width=Math.min(Math.abs(pct),50)+"%"; }
    else      { bar.style.left=(50+pct)+"%"; bar.style.width=Math.min(Math.abs(pct),50)+"%"; }
}

// ── Distribution ────────────────────────────────────────────────────────────
function updateDist(){
    const tot = Object.values(stageCnt).reduce((a,b)=>a+b,0);
    if(!tot) return;
    for(const s of ["W","N1","N2","N3","R","P"]){
        const p = ((stageCnt[s]||0)/tot*100).toFixed(1);
        const f = document.getElementById("df-"+s);
        const t = document.getElementById("dp-"+s);
        if(f) f.style.width = p+"%";
        if(t) t.textContent = p+"%";
    }
}

// ── Charts ──────────────────────────────────────────────────────────────────
function initCharts(){
    Chart.defaults.color="#94a3b8";
    Chart.defaults.font.family="'Inter',sans-serif";
    Chart.defaults.font.size=11;
    const grid = "rgba(255,255,255,.05)";

    chartHR = new Chart(document.getElementById("chartHR"),{
        type:"line",
        data:{labels:[],datasets:[{label:"BPM",data:[],borderColor:"#ef4444",
            backgroundColor:"rgba(239,68,68,.07)",borderWidth:2,fill:true,pointRadius:0,tension:.4}]},
        options:{responsive:true,maintainAspectRatio:false,animation:{duration:200},
            plugins:{legend:{display:false}},
            scales:{x:{grid:{color:grid},ticks:{maxTicksLimit:10}},
                    y:{grid:{color:grid},suggestedMin:40,suggestedMax:130}}}
    });

    chartHypno = new Chart(document.getElementById("chartHypno"),{
        type:"line",
        data:{labels:[],datasets:[{label:"Stage",data:[],borderColor:"#6366f1",
            backgroundColor:"rgba(99,102,241,.07)",borderWidth:2,fill:true,stepped:"before",
            pointRadius:0,tension:0,
            segment:{borderColor:ctx=>{
                const stages=["P","W","N1","N2","N3","R"];
                return (STAGES[stages[ctx.p1.parsed.y]]||{}).color||"#6366f1";
            }}}]},
        options:{responsive:true,maintainAspectRatio:false,animation:{duration:200},
            plugins:{legend:{display:false},
                tooltip:{callbacks:{label:ctx=>{
                    const stages=["P","W","N1","N2","N3","R"];
                    const s=stages[ctx.parsed.y]||"?";
                    return s+" — "+(STAGES[s]||{}).name;
                }}}},
            scales:{x:{grid:{color:grid},ticks:{maxTicksLimit:10}},
                    y:{min:-.5,max:5.5,reverse:true,grid:{color:grid},
                       ticks:{stepSize:1,callback:v=>["P","W","N1","N2","N3","R"][v]||""}}}}
    });
}

function pushChart(chart,label,val){
    chart.data.labels.push(label);
    chart.data.datasets[0].data.push(val);
    if(chart.data.labels.length>MAX_PTS){
        chart.data.labels.shift();
        chart.data.datasets[0].data.shift();
    }
    chart.update("none");
}

// ── Status helpers ──────────────────────────────────────────────────────────
function setDot(type,on){
    document.getElementById("dot-"+type).className = "dot "+(on?"on":"off");
    document.getElementById("lbl-"+type).textContent = type.toUpperCase()+(on?" ON":" OFF");
}

function tick(){
    document.getElementById("clock").textContent =
        new Date().toLocaleTimeString("en-GB",{hour12:false});
}

async function pollStatus(){
    try{
        const r = await fetch(API+"/api/status");
        const d = await r.json();
        setDot("mqtt", d.mqtt);
        document.getElementById("sv-up").textContent = fmtDur(d.uptime);
        document.getElementById("sv-acc").textContent = (d.accuracy*100).toFixed(1)+"%";
    }catch(e){ setDot("mqtt",false); }
}

function fmtDur(s){
    if(s<60) return Math.round(s)+"s";
    if(s<3600) return Math.floor(s/60)+"m";
    return Math.floor(s/3600)+"h "+Math.floor((s%3600)/60)+"m";
}

// ── Simulate ────────────────────────────────────────────────────────────────
function doSim(){ fetch(API+"/api/simulate",{method:"POST"}).catch(()=>{}); }
function toggleAuto(){
    const btn=document.getElementById("btn-auto");
    if(autoTmr){ clearInterval(autoTmr); autoTmr=null; btn.classList.remove("on"); btn.textContent="Auto"; }
    else{ autoTmr=setInterval(doSim,800); btn.classList.add("on"); btn.textContent="Stop"; }
}
