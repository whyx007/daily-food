"""反软广规则：纯规则、可解释、零外部依赖。

每条线索（一段推荐文案/标题）进来，命中哪些信号、各扣/加多少分，全部记录。
"""
import re

# 商业推广信号（强）
COMMERCIAL = [
    (r"团购|优惠券|优惠码|返现|返佣|下单链接|小黄车|商品链接|点击购买|领券", "挂团购/返佣链接", -0.50),
    (r"私信我|后台回复|加微|加V|vx|微信咨询|合作请", "导流/商业合作", -0.30),
    (r"探店|商务合作|广告|推广|品牌方", "自述商业属性", -0.15),
]

# 模板化文案（中）
TEMPLATE = [
    (r"绝了|yyds|天花板|闭眼冲|无敌|封神|强烈安利|宝藏店铺|好吃到哭|一口封神", "套话密度高", -0.30),
    (r"必吃|首家|唯一|全网最|本地人都不知道", "夸张绝对化表述", -0.15),
]

# 不可验证（中）
UNVERIFIABLE = [
    (r"环境|氛围|出片|打卡|宝藏|治愈|幸福感", "只谈氛围不谈食物", -0.10),
]

# 正面信号（可信）
POSITIVE = [
    (r"(老板|店家|店主)(姓|叫)|开了\\s*\\d+\\s*年|几十年|老店|家庭作坊", "提到店主/经营年限", +0.20),
    (r"\\d+\\s*元|\\d+\\s*块|\\d+\\s*两|分量|分量足|加汤|加馍|免费", "有价格/分量等具体细节", +0.20),
    (r"缺点|不足|就是|可惜|略|偏咸|偏油|停车难|环境差|排队久", "主动提缺点", +0.15),
    (r"(早上|中午|下午)\\s*\\d+\\s*点|去晚了|卖完|排队", "提到时段/排队等可验证信息", +0.10),
    (r"西安人|本地人|住了\\d+年|我家楼下|从小吃", "本地人身份", +0.15),
]

ALL_RULES = COMMERCIAL + TEMPLATE + UNVERIFIABLE + POSITIVE


def analyse(text: str) -> dict:
    """返回 {score_delta, signals:[{label, delta}], hits:int}"""
    text = (text or "")
    signals = []
    delta = 0.0
    for pattern, label, weight in ALL_RULES:
        if re.search(pattern, text, flags=re.I):
            signals.append({"label": label, "delta": weight})
            delta += weight
    return {"delta": round(delta, 3), "signals": signals}


def claim_trust(base: float, text: str) -> tuple[float, list]:
    """把信号源的先验可信度与文案信号结合，压到 0.05-1.0。"""
    info = analyse(text)
    value = base + info["delta"]
    value = max(0.05, min(1.0, value))
    return round(value, 3), info["signals"]
