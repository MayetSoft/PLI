"""Participant-facing internationalisation.

Languages: English, French, German, Spanish, Portuguese, Scots.
Negotiation: explicit ?lang= (persisted in a cookie) > cookie >
Accept-Language > English. The organizer console and legal pages are
deliberately not covered here (organizer UI ships in English; legal
pages exist in French and English as controlled documents).

The English strings are canonical. The translations were drafted by a
machine and MUST be reviewed by native speakers before launch — above
all the Scots, and every sentence that carries the safety promises
("never told", "deleted", "voided"): a mistranslated promise is a
broken promise.
"""

from __future__ import annotations

LANGUAGES = ("en", "fr", "de", "es", "pt", "sco")
DEFAULT = "en"


def pick_language(query: str | None, cookie: str | None, accept_header: str) -> str:
    if query in LANGUAGES:
        return query
    if cookie in LANGUAGES:
        return cookie
    for part in accept_header.split(","):
        code = part.split(";")[0].strip().lower()
        primary = code.split("-")[0]
        if code in LANGUAGES:
            return code
        if primary in LANGUAGES:
            return primary
    return DEFAULT


def translate(lang: str, key: str, **kwargs) -> str:
    entry = STRINGS[key]
    text = entry.get(lang) or entry["en"]
    return text.format(**kwargs) if kwargs else text


STRINGS: dict[str, dict[str, str]] = {
    "skip": {
        "en": "Skip to content", "fr": "Aller au contenu", "de": "Zum Inhalt springen",
        "es": "Saltar al contenido", "pt": "Ir para o conteúdo", "sco": "Skip tae the content",
    },
    "footer": {
        "en": "Nothing here persists. Declarations are destroyed at the reveal, matched or not. There are no profiles, no history, no backups.",
        "fr": "Rien ne persiste ici. Les déclarations sont détruites à la révélation, réciproques ou non. Pas de profils, pas d'historique, pas de sauvegardes.",
        "de": "Hier bleibt nichts bestehen. Erklärungen werden bei der Auflösung vernichtet, erwidert oder nicht. Keine Profile, kein Verlauf, keine Sicherungskopien.",
        "es": "Aquí nada persiste. Las declaraciones se destruyen en la revelación, correspondidas o no. Sin perfiles, sin historial, sin copias de seguridad.",
        "pt": "Nada aqui persiste. As declarações são destruídas na revelação, correspondidas ou não. Sem perfis, sem histórico, sem cópias de segurança.",
        "sco": "Naething here bides. Declarations is destroyed at the reveal, matched or no. Nae profiles, nae history, nae backups.",
    },
    "paused": {
        "en": "This event is paused pending review.",
        "fr": "Cet événement est suspendu en attente d'examen.",
        "de": "Diese Veranstaltung ist bis zur Prüfung ausgesetzt.",
        "es": "Este evento está en pausa pendiente de revisión.",
        "pt": "Este evento está em pausa a aguardar revisão.",
        "sco": "This event is paused while it's leukit intae.",
    },
    "open_weekly": {
        "en": "A round is open. It closes Friday at 23:59, Paris time.",
        "fr": "Une manche est ouverte. Elle ferme vendredi à 23 h 59, heure de Paris.",
        "de": "Eine Runde ist offen. Sie schließt Freitag um 23:59 Uhr, Pariser Zeit.",
        "es": "Hay una ronda abierta. Cierra el viernes a las 23:59, hora de París.",
        "pt": "Há uma ronda aberta. Fecha sexta-feira às 23h59, hora de Paris.",
        "sco": "A round is open. It steeks Friday at 23:59, Paris time.",
    },
    "open_event": {
        "en": "The round is open. It closes {closes}. Reveal is {reveal}.",
        "fr": "La manche est ouverte. Elle ferme {closes}. Révélation : {reveal}.",
        "de": "Die Runde ist offen. Sie schließt {closes}. Auflösung: {reveal}.",
        "es": "La ronda está abierta. Cierra {closes}. Revelación: {reveal}.",
        "pt": "A ronda está aberta. Fecha {closes}. Revelação: {reveal}.",
        "sco": "The round is open. It steeks {closes}. The reveal is {reveal}.",
    },
    "scheduled": {
        "en": "The round opens {opens} and closes {closes}. Reveal is {reveal}.",
        "fr": "La manche ouvre {opens} et ferme {closes}. Révélation : {reveal}.",
        "de": "Die Runde öffnet {opens} und schließt {closes}. Auflösung: {reveal}.",
        "es": "La ronda abre {opens} y cierra {closes}. Revelación: {reveal}.",
        "pt": "A ronda abre {opens} e fecha {closes}. Revelação: {reveal}.",
        "sco": "The round opens {opens} an steeks {closes}. The reveal is {reveal}.",
    },
    "closed_weekly": {
        "en": "This week's round is closed. Reveal is Saturday at 08:00, Paris time.",
        "fr": "La manche de cette semaine est fermée. Révélation samedi à 8 h, heure de Paris.",
        "de": "Die Runde dieser Woche ist geschlossen. Auflösung Samstag um 08:00 Uhr, Pariser Zeit.",
        "es": "La ronda de esta semana está cerrada. Revelación el sábado a las 08:00, hora de París.",
        "pt": "A ronda desta semana está fechada. Revelação no sábado às 08h00, hora de Paris.",
        "sco": "This week's round is steekit. The reveal is Setterday at 08:00, Paris time.",
    },
    "closed_event": {
        "en": "The round is closed. Reveal is {reveal}.",
        "fr": "La manche est fermée. Révélation : {reveal}.",
        "de": "Die Runde ist geschlossen. Auflösung: {reveal}.",
        "es": "La ronda está cerrada. Revelación: {reveal}.",
        "pt": "A ronda está fechada. Revelação: {reveal}.",
        "sco": "The round is steekit. The reveal is {reveal}.",
    },
    "voided_weekly": {
        "en": "No round this week.",
        "fr": "Pas de manche cette semaine.",
        "de": "Diese Woche keine Runde.",
        "es": "Esta semana no hay ronda.",
        "pt": "Esta semana não há ronda.",
        "sco": "Nae round this week.",
    },
    "voided_event": {
        "en": "This round did not reach its threshold. Nothing ran, and everything was deleted.",
        "fr": "Cette manche n'a pas atteint son seuil. Rien n'a eu lieu et tout a été supprimé.",
        "de": "Diese Runde hat ihre Schwelle nicht erreicht. Nichts fand statt, alles wurde gelöscht.",
        "es": "Esta ronda no alcanzó su umbral. No se ejecutó nada y todo fue eliminado.",
        "pt": "Esta ronda não atingiu o limiar. Nada aconteceu e tudo foi apagado.",
        "sco": "This round didnae win tae its threshold. Naething ran, an awthing wis deleted.",
    },
    "concluded": {
        "en": "This round has concluded. Everything has been deleted.",
        "fr": "Cette manche est terminée. Tout a été supprimé.",
        "de": "Diese Runde ist abgeschlossen. Alles wurde gelöscht.",
        "es": "Esta ronda ha concluido. Todo ha sido eliminado.",
        "pt": "Esta ronda terminou. Tudo foi apagado.",
        "sco": "This round is by wi. Awthing has been deleted.",
    },
    "none_weekly": {
        "en": "No round this week. The next one opens Monday at 00:00, Paris time.",
        "fr": "Pas de manche cette semaine. La prochaine ouvre lundi à 0 h, heure de Paris.",
        "de": "Diese Woche keine Runde. Die nächste öffnet Montag um 00:00 Uhr, Pariser Zeit.",
        "es": "Esta semana no hay ronda. La próxima abre el lunes a las 00:00, hora de París.",
        "pt": "Esta semana não há ronda. A próxima abre segunda-feira às 00h00, hora de Paris.",
        "sco": "Nae round this week. The neist ane opens Monanday at 00:00, Paris time.",
    },
    "none_event": {
        "en": "No round is scheduled here yet.",
        "fr": "Aucune manche n'est encore programmée ici.",
        "de": "Hier ist noch keine Runde angesetzt.",
        "es": "Aún no hay ninguna ronda programada aquí.",
        "pt": "Ainda não há nenhuma ronda agendada aqui.",
        "sco": "Nae round is set here yet.",
    },
    "ph_email_weekly": {
        "en": "your institutional address", "fr": "votre adresse institutionnelle",
        "de": "Ihre institutionelle Adresse", "es": "tu dirección institucional",
        "pt": "o teu endereço institucional", "sco": "yer institutional address",
    },
    "ph_email": {
        "en": "your email address", "fr": "votre adresse e-mail",
        "de": "Ihre E-Mail-Adresse", "es": "tu dirección de correo",
        "pt": "o teu endereço de e-mail", "sco": "yer email address",
    },
    "ph_code": {
        "en": "event code", "fr": "code de l'événement", "de": "Veranstaltungscode",
        "es": "código del evento", "pt": "código do evento", "sco": "event code",
    },
    "lbl_email": {
        "en": "Email address", "fr": "Adresse e-mail", "de": "E-Mail-Adresse",
        "es": "Dirección de correo", "pt": "Endereço de e-mail", "sco": "Email address",
    },
    "lbl_code": {
        "en": "Event code", "fr": "Code de l'événement", "de": "Veranstaltungscode",
        "es": "Código del evento", "pt": "Código do evento", "sco": "Event code",
    },
    "btn_link": {
        "en": "Send me a sign-in link", "fr": "M'envoyer un lien de connexion",
        "de": "Anmeldelink senden", "es": "Enviarme un enlace de acceso",
        "pt": "Enviar-me uma ligação de acesso", "sco": "Send me a sign-in link",
    },
    "how_title": {
        "en": "How it works", "fr": "Comment ça marche", "de": "So funktioniert es",
        "es": "Cómo funciona", "pt": "Como funciona", "sco": "Hoo it warks",
    },
    "how1_weekly": {
        "en": "A round opens Monday and closes Friday night.",
        "fr": "Une manche ouvre le lundi et ferme le vendredi soir.",
        "de": "Eine Runde öffnet montags und schließt Freitagnacht.",
        "es": "Una ronda abre el lunes y cierra el viernes por la noche.",
        "pt": "Uma ronda abre à segunda-feira e fecha na sexta à noite.",
        "sco": "A round opens Monanday an steeks Friday nicht.",
    },
    "how1_event": {
        "en": "The round opens and closes at the times above.",
        "fr": "La manche ouvre et ferme aux horaires indiqués ci-dessus.",
        "de": "Die Runde öffnet und schließt zu den oben genannten Zeiten.",
        "es": "La ronda abre y cierra en los horarios indicados arriba.",
        "pt": "A ronda abre e fecha nos horários indicados acima.",
        "sco": "The round opens an steeks at the times abuin.",
    },
    "how2": {
        "en": "During the round, you may name up to three people by email address. The three are final — no edits, no withdrawals, no viewing your list.",
        "fr": "Pendant la manche, vous pouvez nommer jusqu'à trois personnes par leur adresse e-mail. Les trois sont définitives — pas de modification, pas de retrait, pas de consultation de votre liste.",
        "de": "Während der Runde können Sie bis zu drei Personen per E-Mail-Adresse benennen. Die drei sind endgültig — kein Bearbeiten, kein Zurückziehen, kein Einsehen Ihrer Liste.",
        "es": "Durante la ronda, puedes nombrar hasta tres personas por su dirección de correo. Las tres son definitivas: sin cambios, sin retiradas, sin ver tu lista.",
        "pt": "Durante a ronda, podes nomear até três pessoas pelo endereço de e-mail. As três são definitivas — sem edições, sem retiradas, sem ver a tua lista.",
        "sco": "While the round is on, ye can name up tae three fowk by email address. The three is final — nae editin, nae takkin back, nae keekin at yer list.",
    },
    "how3": {
        "en": "The people you name are never told. Not now, not later, not ever.",
        "fr": "Les personnes que vous nommez ne sont jamais prévenues. Ni maintenant, ni plus tard, ni jamais.",
        "de": "Die Personen, die Sie benennen, erfahren es nie. Nicht jetzt, nicht später, niemals.",
        "es": "Las personas que nombras nunca lo sabrán. Ni ahora, ni después, ni nunca.",
        "pt": "As pessoas que nomeias nunca são avisadas. Nem agora, nem depois, nem nunca.",
        "sco": "The fowk ye name is never telt. No the noo, no efter, no ever.",
    },
    "how4_weekly": {
        "en": "Saturday morning, if two people named each other, each receives the other's address by email. One message. That is all.",
        "fr": "Le samedi matin, si deux personnes se sont nommées mutuellement, chacune reçoit l'adresse de l'autre par e-mail. Un seul message. C'est tout.",
        "de": "Wenn sich zwei Personen gegenseitig benannt haben, erhält am Samstagmorgen jede die Adresse der anderen per E-Mail. Eine Nachricht. Das ist alles.",
        "es": "El sábado por la mañana, si dos personas se nombraron mutuamente, cada una recibe la dirección de la otra por correo. Un mensaje. Eso es todo.",
        "pt": "No sábado de manhã, se duas pessoas se nomearam mutuamente, cada uma recebe o endereço da outra por e-mail. Uma mensagem. É tudo.",
        "sco": "Setterday morn, gin twa fowk named ilk ither, ilk ane gets the ither's address by email. Ae message. That's aw.",
    },
    "how4_event": {
        "en": "At reveal time, if two people named each other, each receives the other's address by email. One message. That is all.",
        "fr": "À la révélation, si deux personnes se sont nommées mutuellement, chacune reçoit l'adresse de l'autre par e-mail. Un seul message. C'est tout.",
        "de": "Zur Auflösung erhält, wenn sich zwei Personen gegenseitig benannt haben, jede die Adresse der anderen per E-Mail. Eine Nachricht. Das ist alles.",
        "es": "En la revelación, si dos personas se nombraron mutuamente, cada una recibe la dirección de la otra por correo. Un mensaje. Eso es todo.",
        "pt": "Na revelação, se duas pessoas se nomearam mutuamente, cada uma recebe o endereço da outra por e-mail. Uma mensagem. É tudo.",
        "sco": "At the reveal, gin twa fowk named ilk ither, ilk ane gets the ither's address by email. Ae message. That's aw.",
    },
    "how5": {
        "en": "Everything else is deleted, unread and unmatched. Silence.",
        "fr": "Tout le reste est supprimé, jamais lu, jamais révélé. Silence.",
        "de": "Alles andere wird gelöscht, ungelesen und unbeantwortet. Stille.",
        "es": "Todo lo demás se elimina, sin leer y sin corresponder. Silencio.",
        "pt": "Tudo o resto é apagado, por ler e sem correspondência. Silêncio.",
        "sco": "Awthing else is deleted, unread an unmatched. Seelence.",
    },
    "threshold": {
        "en": "If fewer than {n} people sign up, the round is voided and everything is deleted. Nothing is revealed to anyone.",
        "fr": "Si moins de {n} personnes s'inscrivent, la manche est annulée et tout est supprimé. Rien n'est révélé à personne.",
        "de": "Melden sich weniger als {n} Personen an, wird die Runde annulliert und alles gelöscht. Niemandem wird etwas offengelegt.",
        "es": "Si se inscriben menos de {n} personas, la ronda se anula y todo se elimina. No se revela nada a nadie.",
        "pt": "Se menos de {n} pessoas se inscreverem, a ronda é anulada e tudo é apagado. Nada é revelado a ninguém.",
        "sco": "Gin fewer nor {n} fowk sign up, the round is voided an awthing is deleted. Naething is revealed tae naebody.",
    },
    "trust_title": {
        "en": "The trust you are extending", "fr": "La confiance que vous accordez",
        "de": "Das Vertrauen, das Sie gewähren", "es": "La confianza que otorgas",
        "pt": "A confiança que estás a conceder", "sco": "The trust ye're extendin",
    },
    "trust_body": {
        "en": "Addresses are stored as keyed hashes and encrypted blobs, so a copy of the database alone reveals nothing. But the operator holds the key material and could, technically, reconstruct who named whom during a live round. The graph is destroyed at reveal. The source code is public. That is the trust you are extending. If that is not enough — and that is a legitimate position — do not play.",
        "fr": "Les adresses sont stockées sous forme d'empreintes à clé et de blocs chiffrés : une copie de la base seule ne révèle rien. Mais l'opérateur détient les clés et pourrait, techniquement, reconstituer qui a nommé qui pendant une manche en cours. Le graphe est détruit à la révélation. Le code source est public. Voilà la confiance que vous accordez. Si cela ne suffit pas — et c'est une position légitime — ne jouez pas.",
        "de": "Adressen werden als Schlüssel-Hashes und verschlüsselte Blöcke gespeichert; eine Kopie der Datenbank allein verrät nichts. Aber der Betreiber hält das Schlüsselmaterial und könnte technisch rekonstruieren, wer wen während einer laufenden Runde benannt hat. Der Graph wird bei der Auflösung vernichtet. Der Quellcode ist öffentlich. Das ist das Vertrauen, das Sie gewähren. Wenn das nicht genügt — eine legitime Haltung — spielen Sie nicht.",
        "es": "Las direcciones se guardan como hashes con clave y bloques cifrados: una copia de la base de datos por sí sola no revela nada. Pero el operador posee las claves y podría, técnicamente, reconstruir quién nombró a quién durante una ronda en curso. El grafo se destruye en la revelación. El código fuente es público. Esa es la confianza que otorgas. Si no te basta — y es una postura legítima — no juegues.",
        "pt": "Os endereços são guardados como hashes com chave e blocos cifrados: uma cópia da base de dados, por si só, não revela nada. Mas o operador detém as chaves e poderia, tecnicamente, reconstruir quem nomeou quem durante uma ronda ativa. O grafo é destruído na revelação. O código-fonte é público. É essa a confiança que estás a conceder. Se não chega — e é uma posição legítima — não jogues.",
        "sco": "Addresses is keepit as keyed hashes an encryptit blobs, sae a copy o the database alane reveals naething. But the operator hauds the keys an could, technically, rebigg wha named wha while a round is rinnin. The graph is destroyed at the reveal. The source code is public. That's the trust ye're extendin. Gin that's no eneuch — an that's a fair poseetion — dinnae play.",
    },
    "tagline": {
        "en": "No profiles. No photos. No chat. No browsing. No scores. If you both said it, you both find out. Otherwise, nothing happened.",
        "fr": "Pas de profils. Pas de photos. Pas de messagerie. Pas de navigation. Pas de scores. Si vous l'avez dit tous les deux, vous le saurez tous les deux. Sinon, il ne s'est rien passé.",
        "de": "Keine Profile. Keine Fotos. Kein Chat. Kein Stöbern. Keine Punkte. Wenn ihr es beide gesagt habt, erfahrt ihr es beide. Andernfalls ist nichts geschehen.",
        "es": "Sin perfiles. Sin fotos. Sin chat. Sin navegación. Sin puntuaciones. Si ambos lo dijisteis, ambos lo sabréis. Si no, no pasó nada.",
        "pt": "Sem perfis. Sem fotos. Sem chat. Sem navegação. Sem pontuações. Se ambos o disseram, ambos ficam a saber. Caso contrário, nada aconteceu.",
        "sco": "Nae profiles. Nae photies. Nae chat. Nae browsin. Nae scores. Gin ye baith said it, ye baith find oot. Ithergates, naething happened.",
    },
    "report_link": {
        "en": "Report this event", "fr": "Signaler cet événement",
        "de": "Diese Veranstaltung melden", "es": "Denunciar este evento",
        "pt": "Denunciar este evento", "sco": "Report this event",
    },
    "about_link": {
        "en": "What is PLI?", "fr": "Qu'est-ce que PLI ?", "de": "Was ist PLI?",
        "es": "¿Qué es PLI?", "pt": "O que é o PLI?", "sco": "Whit is PLI?",
    },
    "joined_body": {
        "en": "If that address is eligible for this round, a sign-in link has been sent to it. Check the inbox.",
        "fr": "Si cette adresse est éligible pour cette manche, un lien de connexion lui a été envoyé. Consultez la boîte de réception.",
        "de": "Falls diese Adresse für diese Runde zugelassen ist, wurde ihr ein Anmeldelink gesendet. Prüfen Sie den Posteingang.",
        "es": "Si esa dirección es elegible para esta ronda, se le ha enviado un enlace de acceso. Revisa la bandeja de entrada.",
        "pt": "Se esse endereço for elegível para esta ronda, foi-lhe enviada uma ligação de acesso. Verifica a caixa de entrada.",
        "sco": "Gin thon address is eligible for this round, a sign-in link has been sent til it. Check the inbox.",
    },
    "link_ttl": {
        "en": "The link works once and expires in 30 minutes.",
        "fr": "Le lien fonctionne une seule fois et expire au bout de 30 minutes.",
        "de": "Der Link funktioniert einmal und läuft nach 30 Minuten ab.",
        "es": "El enlace funciona una sola vez y caduca a los 30 minutos.",
        "pt": "A ligação funciona uma única vez e expira em 30 minutos.",
        "sco": "The link warks the ance an rins oot in 30 meenits.",
    },
    "invalid": {
        "en": "That link is no longer valid. Links work once and expire after 30 minutes.",
        "fr": "Ce lien n'est plus valide. Les liens fonctionnent une seule fois et expirent après 30 minutes.",
        "de": "Dieser Link ist nicht mehr gültig. Links funktionieren einmal und laufen nach 30 Minuten ab.",
        "es": "Ese enlace ya no es válido. Los enlaces funcionan una vez y caducan a los 30 minutos.",
        "pt": "Essa ligação já não é válida. As ligações funcionam uma vez e expiram após 30 minutos.",
        "sco": "Thon link is nae langer guid. Links wark the ance an rin oot efter 30 meenits.",
    },
    "request_new": {
        "en": "Request a new one.", "fr": "Demander un nouveau lien.",
        "de": "Einen neuen anfordern.", "es": "Solicitar uno nuevo.",
        "pt": "Pedir uma nova.", "sco": "Ask for anither ane.",
    },
    "remaining": {
        "en": "You may name up to three people this round. You have {remaining} remaining.",
        "fr": "Vous pouvez nommer jusqu'à trois personnes cette manche. Il vous en reste {remaining}.",
        "de": "Sie können in dieser Runde bis zu drei Personen benennen. Ihnen verbleiben {remaining}.",
        "es": "Puedes nombrar hasta tres personas esta ronda. Te quedan {remaining}.",
        "pt": "Podes nomear até três pessoas nesta ronda. Restam-te {remaining}.",
        "sco": "Ye can name up tae three fowk this round. Ye hae {remaining} left.",
    },
    "oneway": {
        "en": "This is a one-way door. Once submitted, a name cannot be viewed, changed, or withdrawn — not even by you. If the feeling is mutual, you both hear about it {when}. If it isn't, no one ever knows, including them.",
        "fr": "C'est une porte sans retour. Une fois soumis, un nom ne peut être ni consulté, ni modifié, ni retiré — pas même par vous. Si le sentiment est réciproque, vous l'apprendrez tous les deux {when}. Sinon, personne ne le saura jamais, pas même la personne concernée.",
        "de": "Dies ist eine Einbahntür. Einmal abgeschickt, kann ein Name weder eingesehen noch geändert noch zurückgezogen werden — auch nicht von Ihnen. Beruht das Gefühl auf Gegenseitigkeit, erfahren Sie es beide {when}. Wenn nicht, erfährt es niemand, auch die Person selbst nicht.",
        "es": "Esta es una puerta sin retorno. Una vez enviado, un nombre no puede verse, cambiarse ni retirarse — ni siquiera tú. Si el sentimiento es mutuo, ambos lo sabréis {when}. Si no, nadie lo sabrá nunca, incluida esa persona.",
        "pt": "Esta é uma porta sem retorno. Depois de submetido, um nome não pode ser visto, alterado nem retirado — nem sequer por ti. Se o sentimento for mútuo, ambos ficam a saber {when}. Se não for, ninguém saberá nunca, incluindo essa pessoa.",
        "sco": "This is a yae-wey door. Ance pit in, a name canna be leukit at, chynged, or taen back — no even by yersel. Gin the feelin is mutual, ye baith hear aboot it {when}. Gin it's no, naebody ever kens, includin them.",
    },
    "when_weekly": {
        "en": "Saturday morning", "fr": "samedi matin", "de": "am Samstagmorgen",
        "es": "el sábado por la mañana", "pt": "no sábado de manhã", "sco": "Setterday morn",
    },
    "when_event": {
        "en": "at the reveal", "fr": "à la révélation", "de": "bei der Auflösung",
        "es": "en la revelación", "pt": "na revelação", "sco": "at the reveal",
    },
    "ph_target": {
        "en": "their email address", "fr": "son adresse e-mail", "de": "deren E-Mail-Adresse",
        "es": "su dirección de correo", "pt": "o endereço de e-mail da pessoa", "sco": "their email address",
    },
    "lbl_target": {
        "en": "Email address of the person you name", "fr": "Adresse e-mail de la personne nommée",
        "de": "E-Mail-Adresse der benannten Person", "es": "Correo de la persona que nombras",
        "pt": "E-mail da pessoa que nomeias", "sco": "Email address o the body ye name",
    },
    "btn_seal": {
        "en": "Seal", "fr": "Sceller", "de": "Versiegeln", "es": "Sellar", "pt": "Selar", "sco": "Seal",
    },
    "declare_note": {
        "en": "Leave fields empty to keep declarations for later. The person you name does not need to have signed up — and whether they have is not something this page will ever tell you.",
        "fr": "Laissez des champs vides pour garder des déclarations pour plus tard. La personne que vous nommez n'a pas besoin d'être inscrite — et cette page ne vous dira jamais si elle l'est.",
        "de": "Lassen Sie Felder leer, um Nennungen für später aufzuheben. Die benannte Person muss nicht angemeldet sein — und ob sie es ist, wird Ihnen diese Seite niemals verraten.",
        "es": "Deja campos vacíos para guardar declaraciones para más tarde. La persona que nombras no necesita estar inscrita — y esta página nunca te dirá si lo está.",
        "pt": "Deixa campos vazios para guardar declarações para mais tarde. A pessoa que nomeias não precisa de estar inscrita — e esta página nunca te dirá se está.",
        "sco": "Lea fields toom tae keep declarations for later. The body ye name disnae need tae hae signed up — an whither they hae isnae something this page will ever tell ye.",
    },
    "sealed": {
        "en": "Your three declarations are sealed. Nothing more will happen until {until}.",
        "fr": "Vos trois déclarations sont scellées. Il ne se passera plus rien avant {until}.",
        "de": "Ihre drei Nennungen sind versiegelt. Bis {until} geschieht nichts weiter.",
        "es": "Tus tres declaraciones están selladas. No pasará nada más hasta {until}.",
        "pt": "As tuas três declarações estão seladas. Nada mais acontecerá até {until}.",
        "sco": "Yer three declarations is sealed. Naething mair will happen or {until}.",
    },
    "recorded": {
        "en": "Recorded. Nothing more will happen until {until}.",
        "fr": "Enregistré. Il ne se passera plus rien avant {until}.",
        "de": "Vermerkt. Bis {until} geschieht nichts weiter.",
        "es": "Registrado. No pasará nada más hasta {until}.",
        "pt": "Registado. Nada mais acontecerá até {until}.",
        "sco": "Recordit. Naething mair will happen or {until}.",
    },
    "until_weekly": {
        "en": "Saturday", "fr": "samedi", "de": "Samstag", "es": "el sábado",
        "pt": "sábado", "sco": "Setterday",
    },
    "until_event": {
        "en": "the reveal", "fr": "la révélation", "de": "zur Auflösung",
        "es": "la revelación", "pt": "à revelação", "sco": "the reveal",
    },
    "not_found": {
        "en": "There is nothing at this address.", "fr": "Il n'y a rien à cette adresse.",
        "de": "Unter dieser Adresse gibt es nichts.", "es": "No hay nada en esta dirección.",
        "pt": "Não há nada neste endereço.", "sco": "There's naething at this address.",
    },
    # ---- landing ----
    "land_intro": {
        "en": "PLI is a sealed-envelope service for mutual interest. Everyone in a group privately names the people they hope feel the same. If two people name each other, each receives the other's email address. If not, nothing happens — and no one ever finds out who named whom.",
        "fr": "PLI est un service d'enveloppes scellées pour l'intérêt réciproque. Chacun, dans un groupe, nomme en privé les personnes dont il espère qu'elles ressentent la même chose. Si deux personnes se nomment mutuellement, chacune reçoit l'adresse e-mail de l'autre. Sinon, il ne se passe rien — et personne ne saura jamais qui a nommé qui.",
        "de": "PLI ist ein Dienst versiegelter Umschläge für gegenseitiges Interesse. Jeder in einer Gruppe benennt privat die Menschen, von denen er hofft, dass sie dasselbe empfinden. Benennen sich zwei gegenseitig, erhält jeder die E-Mail-Adresse des anderen. Wenn nicht, geschieht nichts — und niemand erfährt je, wer wen benannt hat.",
        "es": "PLI es un servicio de sobres sellados para el interés mutuo. Cada persona de un grupo nombra en privado a quienes espera que sientan lo mismo. Si dos personas se nombran mutuamente, cada una recibe el correo de la otra. Si no, no pasa nada — y nadie sabrá nunca quién nombró a quién.",
        "pt": "O PLI é um serviço de envelopes selados para o interesse mútuo. Cada pessoa de um grupo nomeia em privado quem espera que sinta o mesmo. Se duas pessoas se nomearem mutuamente, cada uma recebe o e-mail da outra. Caso contrário, nada acontece — e ninguém saberá nunca quem nomeou quem.",
        "sco": "PLI is a sealed-envelope service for mutual interest. Awbody in a group privately names the fowk they howp feels the same. Gin twa fowk name ilk ither, ilk ane gets the ither's email address. Gin no, naething happens — an naebody ever finds oot wha named wha.",
    },
    "rules_title": {
        "en": "The rules, always", "fr": "Les règles, toujours", "de": "Die Regeln, immer",
        "es": "Las reglas, siempre", "pt": "As regras, sempre", "sco": "The rules, aye",
    },
    "rule_reveal": {
        "en": "At the published reveal time, mutual pairs — and only mutual pairs — each receive the other's address. One message. That is all.",
        "fr": "À l'heure de révélation annoncée, les paires réciproques — et elles seules — reçoivent chacune l'adresse de l'autre. Un seul message. C'est tout.",
        "de": "Zur angekündigten Auflösungszeit erhalten gegenseitige Paare — und nur sie — jeweils die Adresse des anderen. Eine Nachricht. Das ist alles.",
        "es": "A la hora de revelación anunciada, las parejas mutuas — y solo ellas — reciben cada una la dirección de la otra. Un mensaje. Eso es todo.",
        "pt": "À hora de revelação anunciada, os pares mútuos — e apenas eles — recebem cada um o endereço do outro. Uma mensagem. É tudo.",
        "sco": "At the set reveal time, mutual pairs — an anely mutual pairs — ilk ane gets the ither's address. Ae message. That's aw.",
    },
    "take_part_title": {
        "en": "Take part", "fr": "Participer", "de": "Mitmachen",
        "es": "Participar", "pt": "Participar", "sco": "Tak pairt",
    },
    "take_part_body": {
        "en": "PLI runs as rounds inside communities and events: a campus week, a conference, a speed-dating night. You join through the link the organizer circulates. Some events are listed publicly:",
        "fr": "PLI fonctionne par manches au sein de communautés et d'événements : une semaine de campus, une conférence, une soirée de speed dating. On y participe via le lien diffusé par l'organisateur. Certains événements sont listés publiquement :",
        "de": "PLI läuft in Runden innerhalb von Gemeinschaften und Veranstaltungen: eine Campus-Woche, eine Konferenz, ein Speed-Dating-Abend. Man nimmt über den Link teil, den der Veranstalter verbreitet. Manche Veranstaltungen sind öffentlich gelistet:",
        "es": "PLI funciona por rondas dentro de comunidades y eventos: una semana de campus, una conferencia, una noche de citas rápidas. Se participa con el enlace que difunde el organizador. Algunos eventos se listan públicamente:",
        "pt": "O PLI funciona por rondas dentro de comunidades e eventos: uma semana de campus, uma conferência, uma noite de speed dating. Participa-se através da ligação que o organizador divulga. Alguns eventos são listados publicamente:",
        "sco": "PLI rins as rounds inby communities an events: a campus week, a conference, a speed-datin nicht. Ye jine throu the link the organizer haunds roond. Some events is listit publicly:",
    },
    "browse_link": {
        "en": "Browse public events", "fr": "Parcourir les événements publics",
        "de": "Öffentliche Veranstaltungen durchsuchen", "es": "Ver eventos públicos",
        "pt": "Ver eventos públicos", "sco": "Brouse public events",
    },
    "run_title": {
        "en": "Run one", "fr": "En organiser un", "de": "Selbst veranstalten",
        "es": "Organiza uno", "pt": "Organiza um", "sco": "Rin ane",
    },
    "run_body": {
        "en": "Organizers create an event, set its own timeline — opens, closes, reveal — restrict it to email domains or a join code, and circulate the link. Organizers see a signup count and the round status. They never see who joined, who named whom, or how many matched.",
        "fr": "Les organisateurs créent un événement, définissent son calendrier — ouverture, fermeture, révélation — le restreignent à des domaines e-mail ou à un code, puis diffusent le lien. Ils voient un nombre d'inscrits et l'état de la manche. Ils ne voient jamais qui s'est inscrit, qui a nommé qui, ni combien se sont trouvés.",
        "de": "Veranstalter erstellen eine Veranstaltung, legen deren Zeitplan fest — Öffnung, Schluss, Auflösung —, beschränken sie auf E-Mail-Domains oder einen Code und verbreiten den Link. Sie sehen eine Anmeldezahl und den Rundenstatus. Sie sehen nie, wer teilnimmt, wer wen benannt hat oder wie viele zueinanderfanden.",
        "es": "Los organizadores crean un evento, fijan su calendario — apertura, cierre, revelación —, lo restringen a dominios de correo o a un código, y difunden el enlace. Ven un número de inscritos y el estado de la ronda. Nunca ven quién se inscribió, quién nombró a quién, ni cuántos coincidieron.",
        "pt": "Os organizadores criam um evento, definem o seu calendário — abertura, fecho, revelação —, restringem-no a domínios de e-mail ou a um código, e divulgam a ligação. Veem um número de inscritos e o estado da ronda. Nunca veem quem se inscreveu, quem nomeou quem, nem quantos se corresponderam.",
        "sco": "Organizers mak an event, set its ain timeline — opens, steeks, reveal — restrick it tae email domains or a jine code, an haund roond the link. They see a sign-up coont an the round status. They never see wha jined, wha named wha, or hoo mony matched.",
    },
    "org_link": {
        "en": "Organizer sign-in", "fr": "Connexion organisateur", "de": "Veranstalter-Anmeldung",
        "es": "Acceso para organizadores", "pt": "Acesso para organizadores", "sco": "Organizer sign-in",
    },
    # ---- directory ----
    "dir_title": {
        "en": "Public events", "fr": "Événements publics", "de": "Öffentliche Veranstaltungen",
        "es": "Eventos públicos", "pt": "Eventos públicos", "sco": "Public events",
    },
    "dir_open": {
        "en": "Open now — closes {closes}.", "fr": "Ouvert — ferme {closes}.",
        "de": "Jetzt offen — schließt {closes}.", "es": "Abierto — cierra {closes}.",
        "pt": "Aberto — fecha {closes}.", "sco": "Open the noo — steeks {closes}.",
    },
    "dir_opens": {
        "en": "Opens {opens}.", "fr": "Ouvre {opens}.", "de": "Öffnet {opens}.",
        "es": "Abre {opens}.", "pt": "Abre {opens}.", "sco": "Opens {opens}.",
    },
    "dir_empty": {
        "en": "No public events at the moment. Most events are private — you reach them through the link their organizer circulates.",
        "fr": "Aucun événement public pour le moment. La plupart des événements sont privés — on y accède par le lien diffusé par leur organisateur.",
        "de": "Derzeit keine öffentlichen Veranstaltungen. Die meisten sind privat — man erreicht sie über den Link ihres Veranstalters.",
        "es": "No hay eventos públicos por el momento. La mayoría son privados: se llega a ellos por el enlace que difunde su organizador.",
        "pt": "Sem eventos públicos de momento. A maioria é privada — chega-se a eles pela ligação que o organizador divulga.",
        "sco": "Nae public events the noo. Maist events is private — ye win at them throu the link their organizer haunds roond.",
    },
    # ---- report ----
    "report_title": {
        "en": "Report this event", "fr": "Signaler cet événement",
        "de": "Diese Veranstaltung melden", "es": "Denunciar este evento",
        "pt": "Denunciar este evento", "sco": "Report this event",
    },
    "report_body": {
        "en": "If this event impersonates an organization, harasses people, or is being used for something it shouldn't be, tell us. Reports are anonymous. Enough independent reports pause the event automatically pending review.",
        "fr": "Si cet événement usurpe l'identité d'une organisation, harcèle des personnes ou sert à autre chose que ce qu'il devrait, dites-le-nous. Les signalements sont anonymes. Un nombre suffisant de signalements indépendants suspend automatiquement l'événement en attente d'examen.",
        "de": "Wenn diese Veranstaltung eine Organisation imitiert, Menschen belästigt oder zweckentfremdet wird, sagen Sie es uns. Meldungen sind anonym. Genügend unabhängige Meldungen setzen die Veranstaltung automatisch bis zur Prüfung aus.",
        "es": "Si este evento suplanta a una organización, acosa a personas o se usa para algo indebido, dínoslo. Las denuncias son anónimas. Suficientes denuncias independientes pausan el evento automáticamente pendiente de revisión.",
        "pt": "Se este evento se faz passar por uma organização, assedia pessoas ou está a ser usado para algo indevido, diz-nos. As denúncias são anónimas. Denúncias independentes suficientes pausam o evento automaticamente até revisão.",
        "sco": "Gin this event maks on tae be some organization, herries fowk, or is bein uised for something it shouldnae be, tell us. Reports is anonymous. Eneuch independent reports pauses the event automatically while it's leukit intae.",
    },
    "report_detail_ph": {
        "en": "anything that helps us assess it (optional)",
        "fr": "tout élément utile à l'évaluation (facultatif)",
        "de": "alles, was uns bei der Einschätzung hilft (optional)",
        "es": "cualquier cosa que ayude a evaluarlo (opcional)",
        "pt": "qualquer coisa que ajude a avaliar (opcional)",
        "sco": "onything that helps us judge it (optional)",
    },
    "lbl_reason": {
        "en": "Reason", "fr": "Motif", "de": "Grund", "es": "Motivo", "pt": "Motivo", "sco": "Raison",
    },
    "lbl_detail": {
        "en": "Details", "fr": "Précisions", "de": "Einzelheiten", "es": "Detalles",
        "pt": "Detalhes", "sco": "Details",
    },
    "btn_report": {
        "en": "Report", "fr": "Signaler", "de": "Melden", "es": "Denunciar",
        "pt": "Denunciar", "sco": "Report",
    },
    "reported_body": {
        "en": "Thank you. The report has been recorded and will be reviewed.",
        "fr": "Merci. Le signalement a été enregistré et sera examiné.",
        "de": "Danke. Die Meldung wurde erfasst und wird geprüft.",
        "es": "Gracias. La denuncia ha sido registrada y será revisada.",
        "pt": "Obrigado. A denúncia foi registada e será revista.",
        "sco": "Thank ye. The report has been recordit an will be leukit at.",
    },
    "reason_impersonation": {
        "en": "impersonation", "fr": "usurpation d'identité", "de": "Identitätsmissbrauch",
        "es": "suplantación", "pt": "falsidade de identidade", "sco": "impersonation",
    },
    "reason_harassment": {
        "en": "harassment", "fr": "harcèlement", "de": "Belästigung",
        "es": "acoso", "pt": "assédio", "sco": "harassment",
    },
    "reason_spam": {
        "en": "spam", "fr": "spam", "de": "Spam", "es": "spam", "pt": "spam", "sco": "spam",
    },
    "reason_other": {
        "en": "other", "fr": "autre", "de": "Sonstiges", "es": "otro", "pt": "outro", "sco": "ither",
    },
    "sso_link": {
        "en": "Or sign in through your institution",
        "fr": "Ou connectez-vous via votre établissement",
        "de": "Oder über Ihre Einrichtung anmelden",
        "es": "O accede a través de tu institución",
        "pt": "Ou entra através da tua instituição",
        "sco": "Or sign in throu yer institution",
    },
    "legal_links": {
        "en": "Privacy · Terms", "fr": "Confidentialité · Conditions",
        "de": "Datenschutz · Bedingungen", "es": "Privacidad · Condiciones",
        "pt": "Privacidade · Termos", "sco": "Privacy · Terms",
    },
}
