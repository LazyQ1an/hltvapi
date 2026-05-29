from __future__ import annotations

import math
import re
import time as tmod
import asyncio
from typing import Any


class BlockDetector:
    """
    濠电姷鏁告慨浼村垂婵傜鏄ラ柡宥庡幗閸ゅ苯螖閿濆懎鏆為柛?Block 婵犵數濮烽。钘壩ｉ崨鏉戠；闁逞屽墴閺屾稓鈧綆鍋呯亸鎵磼缂佹娲寸€殿喖鐖奸獮瀣敇閻愭彃顥愰梻鍌氬€风欢锟犲窗閺嶎収鏁嬫い鎾跺У椤?v2闂?
    闂傚倸鍊风粈渚€骞栭銈囩煋闁割偅娲嶉埀顒婄畵瀹曞ジ濮€閵忋垹顦╁┑掳鍊х徊浠嬪疮椤愩倖鍏滈柍褜鍓熷娲箹閻愭彃濮夐梺鍝勬噽婵炩偓闁诡喕鍗抽獮妯肩磼濡厧寮?    1. 缂傚倸鍊搁崐鎼佸磹閹间礁绐楁慨妯挎硾缁愭鏌￠崶鈺佹灁闁崇懓绉撮埞鎴︽偐閹绘帗娈查梺绋挎捣閸犳牠寮婚妸鈺佸嵆婵ê鍟块崢鈥斥攽閳ュ啿绾ч柛銊ユ健瀵鈽夐姀鐘殿唺闂佺懓顕崕鎰涢妶澶嬧拻濞撴艾娲ら弸娑欍亜閺囥劌骞樻俊?闂傚倸鍊烽懗鍫曞磻閵娾晛纾块柡灞诲劚閽冪喖鏌ㄩ悢鍝勑㈤柣?濠电姷鏁告慨浼村垂婵傜鏄ラ柡宓本鍍甸梺闈涱焾閸庢垶鎯旈…鎴炴櫓闂佸吋浜介崕閬嶅礉閸涘瓨鈷戦柟绋垮绾剧敻鏌涚€ｎ偅灏柍瑙勫灴椤㈡瑩骞嗚濡叉劙鎮楀▓鍨灈闁绘牜鍘ч悾宄邦潨閳ь剟銆佸鈧幃鈺呭箛娴ｅ湱绋戦梻鍌氬€风粈渚€骞夐敍鍕殰闁圭儤鍤﹀☉姘ｅ亾闂堟稒鍟炴い顐ｆ礃缁绘繈妫冨☉鍗炲壉闂佹悶鍊愰崑鎾绘煟鎼粹€冲辅闁稿鎹囬弻娑㈠即閵娿儱顫╁銈庡亾缁辨洜妲愰幘瀛樺闁告繂瀚呭☉銏＄厱閻庯綆鍋呭畷宀勬煛鐏炲墽鈽夐摶鏍归敐鍛础妞わ负鍎崇槐鎾存媴鐟欏嫷妫冨銈冨劜閹歌崵绮嬪澶婄濞达絽鎲￠ˉ婵嬫⒑閸撹尙鍘涢柛鐘崇鐎靛ジ宕奸妷锔规嫼?    2. 闂傚倸鍊烽懗鍫曞储瑜旈妴鍐╂償閵忋埄娲稿銈呯箰閻楀棝鎮為崹顐犱簻闁瑰搫妫楁禍楣冩⒑缁嬪尅宸ラ柟鑺ョ矒閹崇偤鏌嗗鍛版憰闂侀潧顦崕鎶芥偩閹惰姤鈷戦梻鍫熺〒缁犲啿鈹戦锝呭箹閸楅亶鏌ゆ慨鎰偓妤冨閸忚偐绠鹃柟瀵稿仧閹冲懎顭胯娴滃爼寮?闂傚倸鍊烽懗鍫曞磻閵娾晛纾块柡灞诲劚閽冪喖鏌ㄩ悢鍝勑㈤柣?婵犵數濮烽。钘壩ｉ崨鏉戠；闁逞屽墴閺屾稓鈧綆鍋呯亸鎵磼缂佹娲寸€殿喖鐖奸獮瀣敇閻愭彃顥嶉梻?block 闂傚倸鍊风粈渚€骞夐敓鐘冲殞闁诡垼鐏愮憴鍕垫Ч閹肩补鈧磭浜板┑鐐存綑閸氬顭囧▎鎴犵焼闁告洦鍨遍悡鐔兼煙鐎甸晲绱冲┑鍌滎焾缁€鍡涙煙閻戞ê鐒鹃柣鏂挎閹銈﹂幐搴哗閻庢稒绻勭槐鎾诲磼濮橆兘鍋撹ぐ鎺戠濡わ絽鍟粻顖炴倵閿濆骸娅橀柡浣割儔閺屾盯鍩勯崘顏呭櫘濡炪倧鑵归弲鐘诲箖濡ゅ懏鍊烽柣鐔稿閸嬫捇寮介鐐碉紵闂佸吋绁撮弲婊冪暦閸欏绡€濠电姴鍊绘晶鏇熸交濠靛洨绠鹃弶鍫濆⒔閹吋銇勯鐐靛ⅵ鐎殿喖鎲￠幆鏃堝Ω閿旀儳骞堟繝寰锋澘鈧劙宕戦幘缁樼厽閹烘娊宕濆畝鍕ㄢ偓鏃堝礃椤旇偐锛滈梺缁樺姉鐞涖儵骞忔繝姘厸濠㈣泛锕︽晶鏇烆熆瑜忛弲顐ゅ垝?    3. 闂傚倸鍊风粈渚€骞夐敓鐘虫櫔婵犵妲呴崑鍛淬€冩径鎰﹂柟閭﹀枟瀹曞霉閿濆棙绀堥柛鐘崇墵瀹曞綊骞嗚閺嗭箓鏌涢妷銏℃珦闁衡偓閵娾晜鈷戦悹鍥ㄥ絻椤掋垽鏌涢幇顖氬惞缂佽鲸鎸搁～婵嬪础閻愭畫?闂傚倸鍊烽懗鍫曞磻閵娾晛纾块柡灞诲劚閽冪喖鏌ㄩ悢鍝勑㈤柣?闂傚倷娴囧畷鍨叏閹惰姤鍊块柨鏇楀亾妞ゎ厼鐏濊灒闁兼祴鏅濋ˇ?block 婵犵數濮烽。钘壩ｉ崨鏉戝瀭妞ゅ繐鐗嗛悞鍨亜閹哄棗浜剧紒鍓ц檸閸樻儳鈽夐悽绋跨劦妞ゆ帒瀚埛鎴︽煙缁嬫寧鎹ｉ柍钘夘樀閺岋綁顢橀悙娴嬪亾閸ф违闁稿瞼鍋涢悡娑樏归悡搴¤埞婵犫偓闁秴鐒垫い鎺戯功缁夌敻鏌涢悩鍏呬孩闁靛洦鍔欓、娑橆潩閸忕厧鐦滈梺璇插嚱缂嶅棙绂嶉鍫濈煑闁告洦鍓涚粻楣冩煕濞戝崬鏋熺€规洖鐬奸埀顒侇問閸ｎ噣宕抽敐澶婄疇婵犲﹤鍟犻弸鏃堟煕椤垵鏋熼柡?    4. 闂傚倸鍊风粈渚€骞夐敍鍕床闁稿本绮庨惌鎾绘倵閸偆鎽冨┑顔藉▕閺屾稑鈻庤箛锝喰ф繝娈垮灡閹告娊寮婚悢鐓庣闁归偊鍘鹃妴鎰渻閵堝啫鍔滄い銊ョ墦閸┾偓妞ゆ帒鍊归弳顒併亜閿濆繐顩紒顔肩墛閹峰懏銈﹂崹顔?闂傚倸鍊烽懗鍫曞磻閵娾晛纾块柡灞诲劚閽冪喖鏌ㄩ悢鍝勑㈤柣?闂傚倸鍊风粈渚€骞栭鈷氭椽濡歌瀹曞弶绻濋棃娑氬閻忓繐閰ｉ幃妤呮偨閻㈢偣鈧﹪鏌涚€ｎ偅宕屾俊顐㈠暙閳藉顫濋崣妯肩濠?Cloudflare/HLTV 闂傚倸鍊烽懗鍓佸垝椤栫偑鈧啴宕奸妷銉х枃闂佽宕橀崺鏍敃閼恒儳绠鹃柟瀛樼懃閻忊晝绱掗埀顒€鐣濋埀顒勫箟閹间焦鍋嬮柛顐ｇ箘閻熴劑鏌?    5. 濠电姷鏁告慨顓㈠箯閸愵喖宸濇い鎾寸箖椤洟姊绘笟鈧鑽ゅ緤娴犲绠规い鎰╁劤娴滈亶姊绘笟鈧埀顒傚仜閼活垱鏅堕鈧Λ?闂傚倸鍊烽懗鍫曞磻閵娾晛纾块柡灞诲劚閽冪喖鏌ㄩ悢鍝勑㈤柣?闂傚倸鍊风粈渚€骞夐敓鐘冲仭妞ゆ牗绋撻々鍙夌節婵犲倻澧遍柡浣割儐閵囧嫰寮村Δ鈧禍楣冩倵鐟欏嫭绌跨紒鎻掆偓鐔轰航闂備礁鎲＄换鍌溾偓姘卞厴瀹曢潧鈻庨幘绮规嫼濠殿喚鎳撳ú銈嗕繆婵傚憡鍊垫慨姗嗗亜瀹撳棛鈧娲樺ú鐔肩嵁濮椻偓椤㈡瑩鎳栭埡濠冃㈤梻鍌欒兌绾爼宕滃┑瀣﹂柣鎰版涧閸ㄦ繈鏌涢…鎴濅簵缂佽妫欓妵鍕箛椤斿吋鐎绘繛瀛樼矋閸庢娊鍩為幋锔藉€烽悗娑欘焽缁嬪洤顪冮妶鍡楃仸闁搞劎鎳撳嵄闁归偊鍏橀弨浠嬫倵閿濆簼绨芥い锔规櫊濡懘顢曢姀鈥愁槱闂佺懓鎲￠崕瀹狀暰閻庡厜鍋撻柛鏇ㄥ墮娴狀垶姊洪幖鐐插姤婵炲鐩幃姗€鎮╃紒妯煎幈?    6. 闂傚倸鍊风粈渚€骞栭锕€瀚夋い鎺嗗亾妞ゎ偄绻楅妵鎰板箳閹寸姴濮︽俊鐐€栭崺鍫ュ礈濞嗗緷娲晝閸屻倖鏅涢梺鍝勭▉閸嬪棛澹?闂傚倸鍊烽懗鍫曞磻閵娾晛纾块柡灞诲劚閽冪喖鏌ㄩ悢鍝勑㈤柣?濠电姷鏁搁崑鐘诲箵椤忓棗绶ら柦妯侯棦瑜版帗鍊婚柤鎭掑劚娴犻箖姊虹化鏇炲⒉妞ゎ厼娲崺鐐差吋婢跺鍘撻梺闈涱槶閸庨亶寮虫潏銊ｄ簻?block 濠电姷鏁搁崑鐐哄垂閸洖绠伴柛婵勫劤閻捇鎮归崫鍕╁仺婵炲樊浜滈柨銈嗕繆閵堝倸浜剧紓浣哄У婵炲﹪寮婚弴鐔风窞婵炴垶姘ㄩ弳鐘差渻閵堝骸浜濇慨濠傤煼閸┾偓妞ゆ帊绶￠崯蹇涙煕閻樺磭澧电€规洘鍔欓獮鏍ㄦ媴閻熼鍑介梻浣稿閸嬪懎煤濮椻偓瀵煡顢楅崒妤€浜鹃柛蹇擃槸娴滈箖姊洪崨濠傚Ё缂佽尪濮ょ粋宥嗐偅閸愨晛鈧爼鏌ｉ幇鐗堟锭濞存粌澧界划顓㈠箣閿旇В鎷婚梺绋挎湰閼归箖顢旈埡鍐＜濠㈣泛锕︾粔娲煕閳规儳浜?    """

    _CF_INDICATORS = [
        "cf-browser-verification",
        "cf_challenge",
        "__cf_chl_f_tk",
        "just a moment...",
        "checking your browser",
        "attention required! | cloudflare",
        "please stand by, while we are checking your browser",
        "_cf_chl_opt",
        "jschl-answer",
        "cf-challenge",
        "challenge-platform",
        "cf-mitigated",
        "cf-error-page",
        "ray id",
        "error reference",
    ]

    # Cloudflare Turnstile indicators (2026 threat model)
    _TURNSTILE_INDICATORS = [
        "turnstile",
        "challenges.cloudflare.com",
        "cdn-cgi/challenge-platform",
        "managed-challenge",
        "cf-turnstile-response",
        "interstitial",
        "cf_chl_rc_m",
        "cf_chl_rc_ni",
        "cf_chl_prog",
        "cf_chl_opt",
    ]

    # IUAM (I'm Under Attack Mode) indicators
    _IUAM_INDICATORS = [
        "under attack mode",
        "ddos protection",
        "checking if the site connection is secure",
        "reviewing the security of your connection",
        "iuam",
    ]

    _HLTV_MARKERS = [
        "HLTV",
        "hltv",
        "match-wrapper",
        "teamsBox",
        "nav-bar",
        "standard-box",
        "header",
        "topnav",
        "sidebar",
        "footer-navigation",
        "match-page",
        "team-row",
        "player-name",
    ]

    _BLOCK_PAGE_SIGNATURES = [
        "access denied",
        "you have been blocked",
        "your ip has been banned",
        "rate limit exceeded",
        "too many requests",
        "please verify you are a human",
        "captcha",
        "recaptcha",
        "hcaptcha",
        "turnstile",
        "bot protection",
        "automated access",
    ]

    _NORMAL_SIZE_RANGE = (5000, 500000)

    def __init__(self) -> None:
        self._response_times: list[float] = []
        self._config: dict[str, Any] = {}

        self._block_history: list[dict[str, Any]] = []
        self._last_normal_hash: str = ""
        self._consecutive_blocks: int = 0
        self._last_block_time: float = 0.0
        self._lock = asyncio.Lock()

    def configure(self, **kwargs: Any) -> None:
        self._config.update(kwargs)

    def check_status(self, status_code: int, url: str) -> str | None:
        if status_code == 429:
            return "rate_limit"
        if status_code == 403:
            return "blocked"
        if status_code == 503:
            return "service_unavailable"
        if status_code >= 400:
            return "http_error"
        return None

    def check_body(self, text: str, url: str) -> str | None:
        text_lower = text.lower()
        has_hltv_markers = self._has_structural_markers(text_lower)

        if not has_hltv_markers:
            for indicator in self._CF_INDICATORS:
                if indicator in text_lower:
                    return "cloudflare_challenge"

            # Turnstile indicators
            for indicator in self._TURNSTILE_INDICATORS:
                if indicator in text_lower:
                    return "cloudflare_turnstile"

            # IUAM indicators
            for indicator in self._IUAM_INDICATORS:
                if indicator in text_lower:
                    return "cloudflare_iuam"
            for sig in self._BLOCK_PAGE_SIGNATURES:
                if sig in text_lower:
                    return "block_page_signature"

        body_size = len(text)
        min_size, max_size = self._NORMAL_SIZE_RANGE

        if body_size < min_size:
            has_marker = any(marker.lower() in text_lower for marker in self._HLTV_MARKERS)
            if not has_marker:
                return "small_body_suspicious"

        if body_size > max_size * 3:
            has_marker = any(marker.lower() in text_lower for marker in self._HLTV_MARKERS)
            if not has_marker:
                return "oversized_body_suspicious"

        html_ratio = self._estimate_html_ratio(text)
        if html_ratio > 0.95 and body_size < 50000:
            has_marker = any(marker.lower() in text_lower for marker in self._HLTV_MARKERS)
            if not has_marker:
                return "high_html_ratio_suspicious"

        if not has_hltv_markers:
            if body_size < 80000:
                return "missing_structural_markers"

        return None

    def check_timing(self, response_time: float) -> str | None:
        if len(self._response_times) < 5:
            return None

        recent = self._response_times[-5:]
        avg_time = sum(recent) / len(recent)
        all_fast = all(t < 0.3 for t in recent)
        all_slow = all(t > 10.0 for t in recent)

        if all_fast and avg_time < 0.3:
            return "consistently_fast"
        if all_slow and avg_time > 10.0:
            return "consistently_slow"

        if len(self._response_times) >= 10:
            older = self._response_times[-10:-5]
            newer = self._response_times[-5:]
            avg_older = sum(older) / len(older)
            avg_newer = sum(newer) / len(newer)
            if avg_older > 0 and avg_newer > avg_older * 3:
                return "response_time_degradation"

        return None

    def record_response_time(self, response_time: float) -> None:
        self._response_times.append(response_time)
        if len(self._response_times) > 30:
            self._response_times = self._response_times[-30:]

    async def combine_checks(
        self,
        status_code: int,
        text: str,
        url: str,
        response_time: float,
    ) -> dict[str, Any]:
        self.record_response_time(response_time)

        details: list[str] = []
        block_type: str | None = None
        scores: list[float] = []

        body_result = self.check_body(text, url)
        if body_result:
            details.append(f"body_check: {body_result}")
            score = self._body_score(body_result)
            scores.append(score)

        status_result = self.check_status(status_code, url)
        if status_result:
            details.append(f"status_check: {status_result}")
            block_type = status_result
            score = self._status_score(status_result)
            scores.append(score)

        if body_result and not status_result:
            block_type = body_result

        timing_result = self.check_timing(response_time)
        if timing_result:
            details.append(f"timing_check: {timing_result}")
            score = self._timing_score(timing_result)
            scores.append(score)

        confidence = self._calculate_confidence(scores, details)

        async with self._lock:
            is_blocked = confidence >= 0.5

            if is_blocked:
                self._consecutive_blocks += 1
                self._last_block_time = tmod.time()
                self._block_history.append({
                    "time": tmod.time(),
                    "type": block_type,
                    "confidence": confidence,
                    "url": url,
                })
                if len(self._block_history) > 100:
                    self._block_history = self._block_history[-50:]
            else:
                self._consecutive_blocks = max(0, self._consecutive_blocks - 1)

            recovery = self._calculate_recovery(is_blocked, confidence)

            return {
                "blocked": is_blocked,
                "block_type": block_type if is_blocked else None,
                "confidence": round(confidence, 3),
                "details": details,
                "recovery": recovery,
                "consecutive_blocks": self._consecutive_blocks,
            }

    def _body_score(self, body_result: str) -> float:
        scoring = {
            "cloudflare_challenge": 1.0,
            "block_page_signature": 0.95,            "cloudflare_turnstile": 0.98,
            "cloudflare_iuam": 0.92,
            "small_body_suspicious": 0.55,
            "missing_structural_markers": 0.55,
            "high_html_ratio_suspicious": 0.4,
            "oversized_body_suspicious": 0.35,
        }
        return scoring.get(body_result, 0.5)

    def _status_score(self, status_result: str) -> float:
        scoring = {
            "rate_limit": 0.95,
            "blocked": 0.9,
            "service_unavailable": 0.7,
            "http_error": 0.4,
        }
        return scoring.get(status_result, 0.3)

    def _timing_score(self, timing_result: str) -> float:
        scoring = {
            "consistently_fast": 0.5,
            "consistently_slow": 0.6,
            "response_time_degradation": 0.45,
        }
        return scoring.get(timing_result, 0.3)

    def _calculate_confidence(self, scores: list[float], details: list[str]) -> float:
        if not scores:
            return 0.0

        max_score = max(scores)
        if len(scores) == 1:
            return max_score

        combined = 1 - math.prod(1 - s for s in scores)

        if "cloudflare_challenge" in str(details):
            combined = max(combined, 0.95)

        return min(1.0, combined)

    def _calculate_recovery(self, is_blocked: bool, confidence: float) -> dict[str, Any]:
        """
        闂傚倷娴囧畷鍨叏瀹曞洦顐介柕鍫濇处椤洟鏌￠崶銉ョ仾闁稿鏅涢埞鎴︽偐鐎圭姴顥濈紓浣哄У鐢繝寮婚弴锛勭杸闁哄洨鍎愰埀顒€鏈穱濠囨嚑鐠哄搫鎯炵紓浣介哺鐢帡鍩ユ径濞炬瀻闁瑰瓨绺鹃幏锟犳⒒娴ｅ憡鎯堟俊顐ｇ懇瀹曟繂鈻庨幇顏嗙畾?
        闂傚倸鍊风粈渚€骞栭銈囩煋闁绘垶鏋荤紞鏍ь熆鐠虹尨鍔熼柡鍡愬€曢湁闁挎繂鐗婇鐘电棯閸撗冧壕闁靛洤瀚板顕€宕剁捄鐑樻毌缂傚倷娴囬褍螞濠靛宓侀柡宥冨妽缂嶅洭鏌涢幘妤€鎳忓▓鎼佹⒒娴ｅ摜绉烘い銉︽尰閺呰泛螖閳ь剟鈥﹂崶銊х瘈婵﹩鍘奸埀顒傚厴閺岋綁濮€閻樺吀绮甸梺?block 婵犵數濮烽弫鎼佸磻濞戞娑樼暆閸曨偆顦┑鐘绘涧椤戝懎效閺屻儲鐓熼柡鍌氱仢閹垿鏌￠崪浣稿闁逞屽墮閸樻粓宕戦幘缁樼厓鐟滄粓宕滃☉銏犵闁圭儤鎸搁閬嶆煛婢跺鐏╂い锔规櫊濮婅櫣绱掑Ο鍨棟濡炪倖娲﹂崢鍓у垝?        - 闂備浇顕уù鐑藉磻閿濆纾规繝闈涚墢绾捐姤鎱ㄥ鈧·鍌炲极婵犲洦鐓曟繛鎴炵懄缂嶆垹绱掗埀顒勫礃椤忎礁浜鹃柣鐔告緲椤忣亝绻濋姀鈽嗙劷缂侇喖锕弻鍡楊吋閸℃瑥骞愰梻浣告啞閸旀垿宕濇惔銊ユ槬闁挎繂妫旂换?        - 闂備浇顕уù鐑藉磻閿濆纾规繝闈涚墢绾捐姤鎱ㄥ鈧·鍌炲极婵犲洦鐓曟繛鎴濆船瀵箖鏌涢妶鍛ⅵ闁哄瞼鍠栭、娑樷槈濮楀棙顥嬬紓鍌欒兌婵潙顭囬敓鐘茶摕婵炴垶鐟х弧鈧梺绋挎湰缁ㄤ粙鏁愭径瀣幐?        - 闂傚倸鍊风粈渚€骞栭銈傚亾濮樺崬鍘寸€规洝顫夌€靛ジ寮堕幋鐘垫毎濠电偞鎸婚崺鍐磻閹剧繝绻嗘い鎰剁磿缁愭棃鏌涢埞鎯т壕婵＄偑鍊栫敮鎺楀磹瑜版帒鐤柛婵嗗▕瑜版帗鏅查柛銉ュ閸旀悂姊虹拠鏌ヮ€楅柕鍫熸倐瀵?transport
        - 闂傚倸鍊风粈渚€骞栭銈傚亾濮樺崬鍘寸€规洝顫夌€靛ジ寮堕幋鐘垫毎濠电偞鎸婚崺鍐磻閹剧繝绻嗘い鎰剁磿缁愭棃鏌涢埞鎯т壕婵＄偑鍊栫敮鎺楀磹瑜版帒鐤柛婵嗗▕瑜版帗鏅查柛銉ュ閸旀悂姊虹拠鏌ヮ€楅柕鍫熸倐瀵?session
        """
        if not is_blocked:
            if self._consecutive_blocks > 0:
                cooldown = min(30.0 * self._consecutive_blocks, 120.0)
                return {
                    "action": "cautious_continue",
                    "cooldown_seconds": 0,
                    "delay_multiplier": 1.0 + self._consecutive_blocks * 0.2,
                    "switch_transport": False,
                    "switch_session": False,
                }
            return {
                "action": "continue",
                "cooldown_seconds": 0,
                "delay_multiplier": 1.0,
                "switch_transport": False,
                "switch_session": False,
            }

        if confidence >= 0.9:
            cooldown = min(60.0 * (2 ** min(self._consecutive_blocks, 5)), 600.0)
            return {
                "action": "full_cooldown",
                "cooldown_seconds": round(cooldown, 1),
                "delay_multiplier": 4.0,
                "switch_transport": self._consecutive_blocks >= 2,
                "switch_session": True,
            }

        if confidence >= 0.7:
            cooldown = min(30.0 * self._consecutive_blocks, 180.0)
            return {
                "action": "moderate_cooldown",
                "cooldown_seconds": round(cooldown, 1),
                "delay_multiplier": 2.5,
                "switch_transport": self._consecutive_blocks >= 3,
                "switch_session": self._consecutive_blocks >= 2,
            }

        if confidence >= 0.5:
            return {
                "action": "soft_throttle",
                "cooldown_seconds": 5.0,
                "delay_multiplier": 1.5,
                "switch_transport": False,
                "switch_session": self._consecutive_blocks >= 4,
            }

        return {
            "action": "continue",
            "cooldown_seconds": 0,
            "delay_multiplier": 1.0,
            "switch_transport": False,
            "switch_session": False,
        }

    def get_block_pattern(self) -> dict[str, Any]:
        """
        闂傚倸鍊风粈渚€骞夐敍鍕殰闁圭儤鍤﹀☉妯锋瀻闁圭偓娼欓埀?block 闂傚倸鍊风粈渚€骞夐敓鐘虫櫔婵犵妲呴崑鍛淬€冩径鎰﹂柟閭﹀枟瀹曞霉閿濆棙绀堥柛鐘崇墵瀹曞綊骞嗚閺嗭箓鏌涢妷銏℃珦闁衡偓閵娾晜鈷掑ù锝囨嚀椤曟粎绱掔€ｎ偄鐏撮柟顖氼槹缁虹晫绮欓幐搴ｂ偓顒勬⒑闂堟稓澧曟俊顐ｇ洴閵嗗懘寮婚妷銉ь啇闂佸湱鈷堥崢楣冨储濞戙垺鐓涢柛鈩兩戠粈鍐磼缂佹娲寸€殿喖鐖奸獮瀣敇閻愭彃顥撻梻鍌欒兌缁垳鎹㈠澶婄獥婵°倕鎯ら崶顒佸亱闁割偆鍠庨崝鍛存⒑闂堟侗鐓┑鈥虫穿閵囨劙鎮㈤崗灏栨嫼闂佸憡绻傜€氼剟寮抽姀銈嗙厱闁冲搫鍊绘晶鍨亜閵忥紕鎳冮柣锝嗙箞瀹曠喖顢?        """
        if not self._block_history:
            return {"pattern": "none", "risk_level": "low"}

        now = tmod.time()
        recent = [h for h in self._block_history if now - h["time"] < 3600]

        if not recent:
            return {"pattern": "none_recent", "risk_level": "low"}

        types: dict[str, int] = {}
        for h in recent:
            t = h.get("type", "unknown")
            types[t] = types.get(t, 0) + 1

        avg_confidence = sum(h["confidence"] for h in recent) / len(recent)

        if len(recent) > 5 and avg_confidence > 0.7:
            risk = "high"
        elif len(recent) > 2:
            risk = "medium"
        else:
            risk = "low"

        return {
            "pattern": "active_blocking",
            "risk_level": risk,
            "recent_blocks": len(recent),
            "block_types": types,
            "avg_confidence": round(avg_confidence, 2),
        }

    def _estimate_html_ratio(self, text: str) -> float:
        if not text:
            return 0.0
        tag_chars = len(re.findall(r'<[^>]+>', text)) * 2
        return min(1.0, tag_chars / max(1, len(text)))

    def _has_structural_markers(self, text_lower: str) -> bool:
        count = sum(1 for marker in self._HLTV_MARKERS if marker.lower() in text_lower)
        return count >= 2

    def reset_pattern(self) -> None:
        self._response_times.clear()
        self._consecutive_blocks = 0
