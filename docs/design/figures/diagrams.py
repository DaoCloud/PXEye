"""Generate modules.svg and resources.svg (then: rsvg-convert -z 2 x.svg -o x.png)."""
B, G = "#1F4E79", "#44546A"

class Fig:
    def __init__(self, w, h):
        self.w, self.h, self.o = w, h, []
    def band(self, x, y, w, h, title, fill="#F4F6F9", stroke="#BFC9D6", tc=G, bottom=False):
        ty = y + h - 12 if bottom else y + 22
        self.o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
                      f'<text x="{x+14}" y="{ty}" font-size="14" fill="{tc}">{title}</text>')
    def box(self, x, y, w, h, t, sub=None, dark=False, dashed=False):
        f = B if dark else "#FFFFFF"; c = "#FFFFFF" if dark else "#111111"; sc = "#FFFFFF" if dark else G
        d = ' stroke-dasharray="6,4"' if dashed else ''
        self.o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{f}" stroke="{B}" stroke-width="1.5"{d}/>')
        if sub:
            self.o.append(f'<text x="{x+w/2}" y="{y+h/2-3}" text-anchor="middle" font-size="15" font-weight="600" fill="{c}">{t}</text>'
                          f'<text x="{x+w/2}" y="{y+h/2+16}" text-anchor="middle" font-size="11.5" fill="{sc}">{sub}</text>')
        else:
            self.o.append(f'<text x="{x+w/2}" y="{y+h/2+5}" text-anchor="middle" font-size="15" font-weight="600" fill="{c}">{t}</text>')
    def arrow(self, x1, y1, x2, y2, label=None, lx=None, ly=None, anchor="middle", dashed=False):
        d = ' stroke-dasharray="6,4"' if dashed else ''
        self.o.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{G}" stroke-width="1.6" marker-end="url(#ae)"{d}/>')
        if label:
            lx = (x1 + x2) / 2 if lx is None else lx; ly = (y1 + y2) / 2 - 7 if ly is None else ly
            self.o.append(f'<text x="{lx}" y="{ly}" font-size="12" fill="{G}" text-anchor="{anchor}">{label}</text>')
    def text(self, x, y, t, size=12, anchor="start"):
        self.o.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{G}" text-anchor="{anchor}">{t}</text>')
    def save(self, path):
        open(path, "w").write(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" font-family="PingFang SC, Heiti SC, sans-serif">'
            f'<defs><marker id="ae" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="{G}"/></marker></defs>'
            f'<rect width="{self.w}" height="{self.h}" fill="white"/>{"".join(self.o)}</svg>')

# ---- module dependencies ----
m = Fig(1290, 500)
X = [30, 290, 550, 810, 1070]          # 站点 → 网络 → 清单 → 机柜 → 交付
m.box(940, 30, 190, 70, "健康", "告警 · 阻止分配")
m.box(X[0], 205, 190, 70, "站点", "依赖组件就绪")
m.box(X[1], 205, 190, 70, "网络", "子网 · DHCP · 地址分配")
m.box(X[2], 205, 190, 70, "清单", "到货清单 → 期望清单")
m.box(X[3], 205, 190, 70, "机柜", "发现 · 对账 · 上线 · 维护", dark=True)
m.box(X[4], 205, 190, 70, "交付", "装机 · 验收 · 移交")
m.box(940, 400, 190, 70, "档案与审计", "固件基线 · 安装方案 · 审计")
for i, (top, bottom) in enumerate([("组件就绪", ""), ("子网与", "可分配地址"), ("期望的机柜", "域与设备"), ("就绪状态", "")]):
    m.arrow(X[i] + 190, 240, X[i + 1] - 2, 240, top)
    if bottom: m.text(X[i] + 225, 262, bottom, anchor="middle")
m.arrow(985, 100, 925, 203); m.arrow(1085, 100, 1145, 203); m.text(1035, 160, "阻止分配的告警", anchor="middle")
m.arrow(950, 400, 878, 277, "固件基线", lx=900, ly=350, anchor="end")
m.arrow(925, 277, 997, 398)
m.arrow(1120, 400, 1192, 277, "安装方案", lx=1170, ly=350, anchor="start")
m.arrow(1145, 277, 1073, 398); m.text(1035, 335, "操作与结果", anchor="middle")
m.save("modules.svg")

# ---- resource relationships ----
r = Fig(1340, 770)
CX, DX = 640, 1030            # left edge of bands C and D
r.band(30, 50, 200, 580, "人工输入")
r.band(280, 50, 260, 580, "期望清单（NICo）", "#EAF1F8", "#2E75B6", B)
r.band(CX, 50, 280, 580, "对象与状态（NICo）", "#EAF1F8", "#2E75B6", B)
r.band(DX, 50, 280, 580, "执行与交付（NICo）", "#EAF1F8", "#2E75B6", B)
r.band(30, 655, 1280, 95, "平台本地数据：均以 NICo 的标识为外键", "#DCE6F2", B, B)
r.box(45, 260, 170, 70, "到货清单", "唯一的人工输入", dark=True)
r.box(300, 110, 220, 70, "期望的 NVLink 域"); r.box(300, 260, 220, 70, "期望的机柜", "机柜 ID · 规格由推导得出")
r.box(300, 410, 220, 70, "期望的托盘", "计算 · 交换机 · 供电框")
c, d = CX + 30, DX + 30       # box left edges
r.box(c, 110, 220, 70, "NVLink 域"); r.box(c, 260, 220, 70, "机柜", "状态机 · 健康")
r.box(c, 410, 220, 70, "托盘", "计算 · 交换机 · 供电框"); r.box(c, 540, 220, 70, "DPU", "计算托盘的子对象")
r.box(d, 110, 220, 70, "机柜规格", "成员数量 · 固件清单", dashed=True)
r.box(d, 260, 220, 70, "任务", "上线 · 电源 · 固件")
r.box(d, 410, 220, 70, "实例"); r.box(d, 540, 220, 70, "租户 / 上层平台")
for i, t in enumerate(["清单版本", "固件基线", "安装方案", "安装任务", "审计记录"]):
    r.box(330 + i * 195, 690, 165, 44, t)
r.arrow(215, 280, 298, 150); r.arrow(215, 295, 298, 295, "生成"); r.arrow(215, 310, 298, 440)
r.arrow(410, 258, 410, 182, "归属", lx=420, ly=225, anchor="start")
r.arrow(410, 408, 410, 332, "机柜 ID 与槽位", lx=420, ly=375, anchor="start")
g1 = (540 + CX) / 2; g2 = (CX + 280 + DX) / 2   # centres of the gaps between bands
r.arrow(520, 145, c - 2, 145); r.arrow(520, 295, c - 2, 295, "发现后生成", lx=g1); r.arrow(520, 445, c - 2, 445)
r.arrow(c + 110, 258, c + 110, 182, "归属", lx=c + 120, ly=225, anchor="start")
r.arrow(c + 110, 408, c + 110, 332, "机柜 ID 与槽位", lx=c + 120, ly=375, anchor="start")
r.arrow(c + 110, 480, c + 110, 538, "包含", lx=c + 120, ly=514, anchor="start")
r.arrow(d, 165, c + 222, 268, dashed=True); r.text(g2, 200, "约束", anchor="middle")
r.arrow(d, 295, c + 222, 295, "作用于", lx=g2); r.text(g2, 317, "机柜 · 域 · 托盘", anchor="middle")
r.arrow(c + 220, 445, d - 2, 445, "就绪后分配", lx=g2)
r.arrow(d + 110, 480, d + 110, 538, "交付", lx=d + 120, ly=514, anchor="start")
r.save("resources.svg")
