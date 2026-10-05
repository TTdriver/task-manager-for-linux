#!/usr/bin/env python3
"""Windows-inspired system monitor for Linux. No administrator access required."""
import os
import platform
import queue
import threading
import time
from collections import deque
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
import psutil

BG='#171717'; PANEL='#202020'; TEXT='#f1f1f1'; MUTED='#aaaaaa'
COLORS={'CPU':'#67c6ee','Memory':'#bb8eea','Disk':'#8bd497','Network':'#efa968'}

def size(n):
    for unit in ('B','KB','MB','GB','TB'):
        if abs(n)<1024:return f'{n:.1f} {unit}'
        n/=1024
    return f'{n:.1f} PB'

class Collector:
    def __init__(self):
        self.previous=None
        self.cpu_ready=False
    def sample(self):
        now=time.monotonic();disk=psutil.disk_io_counters();net=psutil.net_io_counters(pernic=True)
        # Exclude loopback to avoid counting local application traffic twice.
        received=sum(v.bytes_recv for k,v in net.items() if k!='lo')
        sent=sum(v.bytes_sent for k,v in net.items() if k!='lo')
        cpu=psutil.cpu_percent();cores=psutil.cpu_percent(percpu=True)
        memory=psutil.virtual_memory();swap=psutil.swap_memory()
        read=write=rx=tx=0.0
        if self.previous:
            old,od,orn,osn=self.previous;dt=max(now-old,.001)
            if disk and od:
                read=max(0,disk.read_bytes-od.read_bytes)/dt
                write=max(0,disk.write_bytes-od.write_bytes)/dt
            rx=max(0,received-orn)/dt;tx=max(0,sent-osn)/dt
        self.previous=(now,disk,received,sent)
        processes=[]
        for p in psutil.process_iter(['pid','name','username','memory_info','status','create_time']):
            try:
                info=p.info;mi=info['memory_info']
                processes.append({'pid':p.pid,'name':info['name'] or '?','user':info['username'] or '—',
                    'cpu':p.cpu_percent()/max(psutil.cpu_count() or 1,1),'memory':mi.rss if mi else 0,
                    'status':info['status'] or '—','created':info['create_time']})
            except (psutil.NoSuchProcess,psutil.AccessDenied,psutil.ZombieProcess):pass
        freq=psutil.cpu_freq()
        disks=[]
        for part in psutil.disk_partitions():
            try:
                usage=psutil.disk_usage(part.mountpoint)
                disks.append((part.device,part.mountpoint,part.fstype,size(usage.total),size(usage.free),f'{usage.percent:.0f}%'))
            except (PermissionError,OSError):pass
        data=dict(cpu=cpu if self.cpu_ready else None,cores=cores,memory=memory,swap=swap,read=read,write=write,rx=rx,tx=tx,
            processes=processes,freq=freq.current/1000 if freq else None,uptime=time.time()-psutil.boot_time(),disks=disks)
        self.cpu_ready=True
        return data

class App:
    def __init__(self,root):
        self.root=root;root.title('Task Manager for Linux');root.geometry('1120x760');root.minsize(900,620);root.configure(bg=BG)
        self.closed=threading.Event();self.messages=queue.Queue(maxsize=2);self.collector=Collector();self.data=None
        self.history={k:deque(maxlen=60) for k in COLORS};self.selected='CPU';self.page='Performance'
        self.sort_key='cpu';self.reverse=True;self.process_map={};self.paused=False
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('.',background=PANEL,foreground=TEXT,font=('Sans',10),borderwidth=0)
        style.configure('Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT,rowheight=32,borderwidth=0)
        style.configure('Treeview.Heading',background='#292929',foreground=MUTED,font=('Sans',10,'bold'),padding=8)
        style.map('Treeview',background=[('selected','#304657')],foreground=[('selected',TEXT)])
        style.configure('TEntry',fieldbackground='#303030',foreground=TEXT,insertcolor=TEXT)
        style.configure('TButton',padding=(12,7));style.map('TButton',background=[('active','#404040')])
        header=tk.Frame(root,bg=BG);header.pack(fill='x',padx=24,pady=(20,12))
        self.label(header,'Task Manager',20).pack(side='left')
        self.label(header,platform.node(),10,MUTED).pack(side='right')
        nav=tk.Frame(root,bg=BG);nav.pack(fill='x',padx=24,pady=(0,14))
        self.nav={}
        for page in ('Processes','Performance','Storage'):
            b=tk.Button(nav,text=page,bg=PANEL,fg=TEXT,activebackground='#343434',activeforeground=TEXT,relief='flat',borderwidth=0,highlightthickness=0,padx=20,pady=9,command=lambda p=page:self.show_page(p));b.pack(side='left',padx=(0,8));self.nav[page]=b
        self.pause=ttk.Button(nav,text='Pause updates',command=self.toggle_pause);self.pause.pack(side='right')
        self.body=tk.Frame(root,bg=BG);self.body.pack(fill='both',expand=True,padx=24)
        self.footer=tk.StringVar(value='Collecting live system data…')
        self.label(root,self.footer,9,MUTED).pack(anchor='w',padx=24,pady=12)
        self.show_page('Performance');root.protocol('WM_DELETE_WINDOW',self.close)
        threading.Thread(target=self.worker,daemon=True).start();root.after(100,self.poll)
    def label(self,parent,text,font=11,color=TEXT):
        kw={'textvariable':text} if isinstance(text,tk.Variable) else {'text':text}
        return tk.Label(parent,bg=parent.cget('bg'),fg=color,font=('Sans',font),anchor='w',**kw)
    def worker(self):
        while not self.closed.is_set():
            try:payload=self.collector.sample()
            except Exception as e:payload={'error':str(e)}
            try:self.messages.put_nowait(payload)
            except queue.Full:pass
            self.closed.wait(1)
    def close(self):self.closed.set();self.root.destroy()
    def toggle_pause(self):
        self.paused=not self.paused;self.pause.configure(text='Resume updates' if self.paused else 'Pause updates')
    def show_page(self,page):
        self.page=page
        for widget in self.body.winfo_children():widget.destroy()
        for p,b in self.nav.items():b.configure(bg='#304657' if p==page else PANEL)
        if page=='Performance':self.build_performance()
        elif page=='Processes':self.build_processes()
        else:self.build_storage()
        self.render()
    def build_performance(self):
        sidebar=tk.Frame(self.body,bg=BG,width=220);sidebar.pack(side='left',fill='y',padx=(0,22));sidebar.pack_propagate(False)
        self.cards={}
        for name,color in COLORS.items():
            card=tk.Frame(sidebar,bg=PANEL,highlightthickness=1,highlightbackground=PANEL);card.pack(fill='x',pady=(0,10))
            title=self.label(card,name,13,color);title.pack(anchor='w',padx=16,pady=(13,4))
            value=self.label(card,'Collecting…',10,MUTED);value.pack(anchor='w',padx=16,pady=(0,12))
            mini=tk.Canvas(card,bg=PANEL,height=42,highlightthickness=0);mini.pack(fill='x',padx=12,pady=(0,12))
            self.cards[name]=(card,value,mini)
            for w in (card,title,value,mini):w.bind('<Button-1>',lambda event,n=name:self.select_resource(n))
        main=tk.Frame(self.body,bg=BG);main.pack(side='left',fill='both',expand=True)
        top=tk.Frame(main,bg=BG);top.pack(fill='x',pady=(0,8))
        self.resource_title=self.label(top,self.selected,27);self.resource_title.pack(side='left')
        self.resource_subtitle=self.label(top,'',10,MUTED);self.resource_subtitle.pack(side='right')
        self.graph=tk.Canvas(main,bg=PANEL,highlightthickness=1,highlightbackground='#3c3c3c');self.graph.pack(fill='both',expand=True)
        self.graph.bind('<Configure>',lambda e:self.draw_main())
        axis=tk.Frame(main,bg=BG);axis.pack(fill='x',pady=(5,14))
        self.label(axis,'60 seconds',9,MUTED).pack(side='left')
        self.label(axis,'now',9,MUTED).pack(side='right')
        self.details=tk.StringVar();self.label(main,self.details,20).pack(anchor='w',pady=(0,12))
        self.extra=tk.StringVar();self.label(main,self.extra,10,MUTED).pack(anchor='w',pady=(0,12))
    def select_resource(self,name):self.selected=name;self.render()
    def build_processes(self):
        bar=tk.Frame(self.body,bg=BG);bar.pack(fill='x',pady=(0,12))
        self.search=tk.StringVar();entry=ttk.Entry(bar,textvariable=self.search,width=32);entry.pack(side='left');self.search.trace_add('write',lambda *args:self.render_processes())
        self.label(bar,'  Search name, user, or PID',10,MUTED).pack(side='left')
        ttk.Button(bar,text='End task',command=self.end_task).pack(side='right')
        columns=('name','pid','user','cpu','memory','status');self.tree=self.table(self.body,columns)
        for key,title in zip(columns,('Name','PID','User','CPU %','Memory','Status')):
            self.tree.heading(key,text=title,command=lambda k=key:self.sort(k))
        self.tree.column('name',width=250);self.tree.column('pid',width=75,stretch=False);self.tree.column('cpu',width=85,stretch=False)
        self.label(self.body,'CPU is the share of total machine capacity. End task requests a graceful shutdown.',9,MUTED).pack(anchor='w',pady=10)
    def table(self,parent,columns):
        frame=tk.Frame(parent,bg=PANEL);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=columns,show='headings',selectmode='browse');tree.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(frame,command=tree.yview);scroll.grid(row=0,column=1,sticky='ns');tree.configure(yscrollcommand=scroll.set)
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);horizontal.grid(row=1,column=0,sticky='ew');tree.configure(xscrollcommand=horizontal.set)
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        for c in columns:tree.column(c,width=130,minwidth=70)
        return tree
    def sort(self,key):
        self.reverse=not self.reverse if self.sort_key==key else key in ('cpu','memory');self.sort_key=key;self.render_processes()
    def render_processes(self):
        if not self.data or self.page!='Processes':return
        selected=self.tree.selection();y=self.tree.yview()[0];query=self.search.get().lower()
        rows=[p for p in self.data['processes'] if query in f"{p['name']} {p['pid']} {p['user']}".lower()]
        rows.sort(key=lambda p:p[self.sort_key].lower() if isinstance(p[self.sort_key],str) else p[self.sort_key],reverse=self.reverse)
        self.tree.delete(*self.tree.get_children());self.process_map={}
        for p in rows:
            identity=f"{p['pid']}:{p['created']}";self.process_map[identity]=p
            self.tree.insert('', 'end',iid=identity,values=(p['name'],p['pid'],p['user'],f"{p['cpu']:.1f}",size(p['memory']),p['status']))
        if selected and selected[0] in self.process_map:self.tree.selection_set(selected[0])
        self.tree.yview_moveto(y)
    def end_task(self):
        selected=self.tree.selection()
        if not selected:return
        info=self.process_map.get(selected[0])
        if not info:return
        if info['pid'] in (1,os.getpid()):messagebox.showinfo('Protected task','This task cannot be ended here.');return
        if not messagebox.askyesno('End task',f"Request {info['name']} (PID {info['pid']}) to close? Unsaved work may be lost."):return
        try:
            p=psutil.Process(info['pid'])
            if p.create_time()!=info['created']:raise psutil.NoSuchProcess(info['pid'])
            p.terminate()
        except psutil.NoSuchProcess:messagebox.showinfo('Task closed','This task has already exited.')
        except psutil.AccessDenied:messagebox.showerror('Permission denied','Your account does not have permission to end this task.')
    def build_storage(self):
        self.label(self.body,'Storage',26).pack(anchor='w',pady=(0,15))
        columns=('device','mount','type','total','free','used');self.storage=self.table(self.body,columns)
        for c,t in zip(columns,('Device','Mount point','File system','Capacity','Available','Used')):self.storage.heading(c,text=t)
    def poll(self):
        latest=None
        try:
            while True:latest=self.messages.get_nowait()
        except queue.Empty:pass
        if latest and not self.paused:
            if 'error' in latest:self.footer.set('Could not read system data: '+latest['error'])
            else:
                self.data=latest
                for k,v in [('CPU',latest['cpu']),('Memory',latest['memory'].percent),('Disk',latest['read']+latest['write']),('Network',latest['rx']+latest['tx'])]:
                    if v is not None:self.history[k].append(v)
                self.render()
        if self.paused:self.footer.set('Updates paused')
        self.root.after(150,self.poll)
    def render(self):
        if not self.data:return
        d=self.data;self.footer.set(f"Live • Updated every second     |     {len(d['processes'])} processes     |     Uptime {int(d['uptime']//3600)}h {int(d['uptime']%3600//60)}m")
        if self.page=='Processes':self.render_processes();return
        if self.page=='Storage':
            self.storage.delete(*self.storage.get_children())
            for row in d['disks']:self.storage.insert('','end',values=row)
            return
        memory=d['memory'];summaries={'CPU':f"{d['cpu']:.0f}%" if d['cpu'] is not None else 'Collecting…',
            'Memory':f'{size(memory.total-memory.available)} / {size(memory.total)}  ({memory.percent:.0f}%)',
            'Disk':f"{size(d['read']+d['write'])}/s",'Network':f"↓ {size(d['rx'])}/s   ↑ {size(d['tx'])}/s"}
        for name,(card,label,mini) in self.cards.items():
            card.configure(highlightbackground=COLORS[name] if name==self.selected else PANEL);label.configure(text=summaries[name]);self.plot(mini,list(self.history[name]),COLORS[name],100 if name in ('CPU','Memory') else None,False)
        self.resource_title.configure(text=self.selected);self.resource_subtitle.configure(text={'CPU':f'{psutil.cpu_count()} logical processors','Memory':'Physical memory','Disk':'All disks • read + write','Network':'All interfaces • excluding loopback'}[self.selected])
        self.details.set(summaries[self.selected])
        if self.selected=='CPU':
            self.extra.set(f"Clock speed: {d['freq']:.2f} GHz" if d['freq'] else 'Clock speed unavailable')
        elif self.selected=='Memory':self.extra.set(f"Available: {size(memory.available)}     Swap: {size(d['swap'].used)} / {size(d['swap'].total)}")
        elif self.selected=='Disk':self.extra.set(f"Read: {size(d['read'])}/s     Write: {size(d['write'])}/s")
        else:self.extra.set(f"Receive: {size(d['rx'])}/s     Send: {size(d['tx'])}/s")
        self.draw_main()
    def draw_main(self):
        if self.page=='Performance':self.plot(self.graph,list(self.history[self.selected]),COLORS[self.selected],100 if self.selected in ('CPU','Memory') else None,True)
    def plot(self,canvas,values,color,maximum,grid):
        canvas.delete('all');w=max(canvas.winfo_width(),10);h=max(canvas.winfo_height(),10);top=24 if grid else 3;bottom=h-8
        scale=maximum or max(max(values,default=0)*1.15,1024)
        if grid:
            for i in range(11):
                x=i*w/10;canvas.create_line(x,top,x,bottom,fill='#343434')
            for i in range(6):
                y=top+(bottom-top)*i/5;canvas.create_line(0,y,w,y,fill='#343434')
            canvas.create_text(w-8,10,text=f'{scale:.0f}%' if maximum else size(scale)+'/s',anchor='e',fill=MUTED,font=('Sans',9))
        if len(values)>1:
            coords=[]
            for i,v in enumerate(values):coords.extend((w*(60-len(values)+i)/59,bottom-min(v/scale,1)*(bottom-top)))
            canvas.create_polygon(coords[0],bottom,*coords,coords[-2],bottom,fill='#273b43' if color==COLORS['CPU'] else '#333039',outline='')
            canvas.create_line(*coords,fill=color,width=2)

if __name__=='__main__':
    root=tk.Tk();App(root);root.mainloop()
