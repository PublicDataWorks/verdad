import os
from prefect import task

def optional_task(*args, **kwargs):
    """Decorator that applies Prefect task decorator unless explicitly disabled

    Supports both @optional_task and @optional_task(param=value) syntax

    The decorator is enabled by default and can be disabled by setting
    ENABLE_PREFECT_DECORATOR=false in environment variables.

    Args:
        *args: Variable positional arguments to pass to Prefect task
        **kwargs: Variable keyword arguments to pass to Prefect task

    Returns:
        Function: Original function if Prefect decorator is disabled,
                 or Prefect task-decorated function if enabled
    """
    enable_prefect = os.getenv('ENABLE_PREFECT_DECORATOR', 'true').lower() == 'true'

    if not enable_prefect:
        # If Prefect decorator is disabled, return the function as-is
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        def wrapper(func):
            return func
        return wrapper
    else:
        # If Prefect decorator is enabled (default), apply Prefect task decorator
        def wrapper(func):
            return task(*args, **kwargs)(func)

        # Handle both @optional_task and @optional_task() syntax
        if len(args) == 1 and callable(args[0]) and not kwargs:
            # @optional_task
            return task()(args[0])
        # @optional_task(param=value)
        return wrapper

def optional_flow(*args, **kwargs):
    """Decorator that applies Prefect flow decorator unless explicitly disabled

    Supports both @optional_flow and @optional_flow(param=value) syntax

    The decorator is enabled by default and can be disabled by setting
    ENABLE_PREFECT_DECORATOR=false in environment variables.

    Args:
        *args: Variable positional arguments to pass to Prefect flow
        **kwargs: Variable keyword arguments to pass to Prefect flow

    Returns:
        Function: Original function if Prefect decorator is disabled,
                 or Prefect flow-decorated function if enabled
    """
    enable_prefect = os.getenv('ENABLE_PREFECT_DECORATOR', 'true').lower() == 'true'

    if not enable_prefect:
        # If Prefect decorator is disabled, return the function as-is
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        def wrapper(func):
            return func
        return wrapper
    else:
        # If Prefect decorator is enabled (default), apply Prefect flow decorator
        from prefect import flow

        def wrapper(func):
            return flow(*args, **kwargs)(func)

        # Handle both @optional_flow and @optional_flow() syntax
        if len(args) == 1 and callable(args[0]) and not kwargs:
            # @optional_flow
            return flow()(args[0])
        # @optional_flow(param=value)
        return wrapper

def fetch_radio_stations():
    return [
        {
            "code": "WLEL - 94.3 FM",
            "url": "https://securenetg.com/radio/8090/radio.aac",
            "state": "Georgia",
            "name": "El Gallo",
        },
        {
            "code": "WPHE - 690 AM",
            "url": "https://sp.unoredcdn.net/8124/stream",
            "state": "Pennsylvania",
            "name": "Radio Salvación",
        },
        {
            "code": "WLCH - 91.3 FM",
            "url": "http://streaming.live365.com/a37354",
            "state": "Pennsylvania",
            "name": "Radio Centro",
        },
        {
            "code": "WSDS - 1480 AM",
            "url": "https://s2.mexside.net/6022/stream",
            "state": "Michigan",
            "name": "La Explosiva",
        },
        {
            "code": "WOAP - 1080 AM",
            "url": "http://sparktheo.com:8000/lapoderosa",
            "state": "Michigan",
            "name": "LA Poderosa",
        },
        {
            "code": "WDTW - 1310 AM",
            "url": "http://sh2.radioonlinehd.com:8050/stream",
            "state": "Michigan",
            "name": "La Z",
        },
        {
            "code": "KYAR - 98.3 FM",
            "url": "http://red-c.miriamtech.net:8000/KYAR",
            "state": "Texas",
            "name": "Red C apostolic (college)",
        },
        {
            "code": "KBNL - 89.9 FM",
            "url": "http://wrn.streamguys1.com/kbnl",
            "state": "Texas",
            "name": "Manantial FM",
        },
        {
            "code": "KBIC - 105.7 FM",
            "url": "http://shout2.brnstream.com:8006/;",
            "state": "Texas",
            "name": "Radio Vida",
        },
        {
            "code": "KABA - 90.3 FM",
            "url": "https://radio.aleluya.cloud/radio/8000/stream",
            "state": "Texas",
            "name": "Aleluya Radio",
        },
        {
            "code": "WAXY - 790 AM",
            "url": "http://stream.abacast.net/direct/audacy-waxyamaac-imc",
            "state": "Florida",
            "name": "Radio Libre 790",
        },
        {
            "code": "WLAZ - 89.1 FM",
            "url": "https://sp.unoredcdn.net/8018/stream",
            "state": "Florida",
            "name": "Pura Palabra Radio",
        },
        {
            "code": "KENO - 1460 AM",
            "url": "https://23023.live.streamtheworld.com/KENOAMAAC_SC",
            "state": "Nevada",
            "name": "Deportes Vegas",
        },
        {
            "code": "KNNR - 1400 AM",
            "url": "https://ice42.securenetsystems.net/KNNR",
            "state": "Nevada",
            "name": "KNNR",
        },
        {
            "code": "KCKO - 107.9 FM",
            "url": "https://s5.mexside.net:8000/stream?type=http&nocache=3",
            "state": "Arizona",
            "name": "Mas Radio",
        },
        {
            "code": "KZLZ - 105.3 FM",
            "url": "https://ice42.securenetsystems.net/KZLZ",
            "state": "Arizona",
            "name": "La Poderosa",
        },
        {
            "code": "KCMT - 92.1 FM",
            "url": "https://23023.live.streamtheworld.com/KCMTFMAAC_SC",
            "state": "Arizona",
            "name": "LA Caliente",
        },
        {
            "code": "KRMC - 91.7 FM",
            "url": "http://wrn.streamguys1.com/krmc",
            "state": "Arizona",
            "name": "Radio Cadena Manantial",
        },
        {
            "code": "KNOG - 91.7 FM",
            "url": "http://wrn.streamguys1.com/knog",
            "state": "Arizona",
            "name": "KNOG",
        },
        {"code": "KWST - 1430 AM", "url": "https://s1.voscast.com:10601/xstream", "state": "Arizona", "name": "KWST"},
        {
            "code": "WLMV - 1480 AM",
            "url": "https://14223.live.streamtheworld.com/WLMVAMAAC_SC",
            "state": "Wisconsin",
            "name": "La Movida",
        },
        {
            "code": "WDJA - 1420 AM",
            "url": "https://radio.fiberstreams.com:2020/stream/8702",
            "state": "Florida",
            "name": "Radio Universo 1420",
        },
        {
            "code": "WACC - 830 AM",
            "url": "https://streaming6.locucionar.com:24004/stream",
            "state": "Florida",
            "name": "Radio Paz",
        },
        {
            "code": "WSUA - 1260 AM",
            "url": "https://dvrfl04.tulix.tv/americana2-audio/tracks-a1/mono.m3u8",
            "state": "Florida",
            "name": "America Radio Miami",
        },
        {
            "code": "WURN - 1040 AM",
            "url": "http://ic.streann.com:8000/actualidadam.ogg",
            "state": "Florida",
            "name": "Actualidad 1040",
        },
        {
            "code": "WNMA - 1210 AM",
            "url": "https://stream4.305stream.com:9764/stream",
            "state": "Florida",
            "name": "Radio Mundo",
        },
        {
            "code": "WSRF - 99.5 FM",
            "url": "https://us2.maindigitalstream.com/ssl/WSRF",
            "state": "Florida",
            "name": "Haitian American Radio",
        },
        {
            "code": "SPMN",
            "url": "https://icecast-rian.cdnvideo.ru/voicespa",
            "state": "Russia",
            "name": "Sputnik Mundo",
        },
        {
            "code": "WZHF",
            "url": "https://icecast-rian.cdnvideo.ru/voiceusa",
            "state": "Russia",
            "name": "Radio Sputnik",
        },
        # ===============================================================
        # iHeart Radio Stations
        # ===============================================================
        {
            "code": "K229DB - 93.7 FM",
            "url": "http://stream.revma.ihrhls.com/zc53/hls.m3u8",
            "state": "Arizona",
            "name": "El Patron",
        },
        {
            "code": "KFUE - 106.7 FM",
            "url": "http://17793.live.streamtheworld.com:80/KFUEFMAAC_SC",
            "state": "Arizona",
            "name": "Fuego",
        },
        {
            "code": "KMMA - 97.1 FM",
            "url": "http://stream.revma.ihrhls.com/zc69/hls.m3u8",
            "state": "Arizona",
            "name": "MEGA",
        },
        {
            "code": "RUMBA 4451",
            "url": "http://stream.revma.ihrhls.com/zc4451/hls.m3u8",
            "state": "Arizona",
            "name": "Rumba",
        },
        {
            "code": "WBZW - 96.7 FM",
            "url": "http://stream.revma.ihrhls.com/zc9205/hls.m3u8",
            "state": "Georgia",
            "name": "El Patron",
        },
        {
            "code": "WBZY - 105.7 FM",
            "url": "http://stream.revma.ihrhls.com/zc749/hls.m3u8",
            "state": "Georgia",
            "name": "Z",
        },
        {
            "code": "WRUM HD2 - 97.1 FM",
            "url": "http://stream.revma.ihrhls.com/zc7155/hls.m3u8",
            "state": "Florida",
            "name": "Mega",
        },
        {
            "code": "WRUM - 100.3 FM",
            "url": "http://stream.revma.ihrhls.com/zc605/hls.m3u8",
            "state": "Florida",
            "name": "Rumba",
        },
        {
            "code": "WUMR - 106.1 FM",
            "url": "http://stream.revma.ihrhls.com/zc2001/hls.m3u8",
            "state": "Pennsylvania",
            "name": "Rumba 106.1 PA",
        },
        {
            "code": "WZTU - 94.9 FM",
            "url": "http://stream.revma.ihrhls.com/zc577/hls.m3u8",
            "state": "Florida",
            "name": "Tu",
        },
        {
            "code": "WWFE - 670 AM",
            "url": "http://playerservices.streamtheworld.com/api/livestream-redirect/WWFEAMAAC.aac",
            "state": "Florida",
            "name": "La Poderosa",
        },
        # ===============================================================
        # Arabic language radio stations
        # ===============================================================
        {
            "code": "MCD",
            "url": "https://montecarlodoualiya128k.ice.infomaniak.ch/mc-doualiya.mp3",
            "state": "International",
            "name": "Monte Carlo Doualiya",
        },
        {
            "code": "WMUZ - 1200 AM",
            "url": "https://ais-sa8.cdnstream1.com/prhwjmv4dpl/ct8wcmajf2n",
            "state": "Michigan",
            "name": "Radio Baladi",
        },
        {
            "code": "WNZK - 680 AM",
            "url": "http://wnzk.birach.com:9000/stream",
            "state": "Michigan",
            "name": "WNZK-AM",
        },
        {
            "code": "ARAB",
            "url": "https://s3.radio.co/sc618789ff/listen",
            "state": "Michigan",
            "name": "US Arab Radio",
        },
        # ===============================================================
        # New radio stations
        # ===============================================================
        {
            "code": "WOLS",
            "url": "https://sonos.norsanmedia.com/wols",
            "state": "North Carolina",
            "name": "La Raza"
        },
        {
            "code": "WSRP",
            "url": "https://radioenhd.com:7108/;",
            "state": "North Carolina",
            "name": "La Grande"
        },
        {
            "code": "WIST",
            "url": "https://sonos.norsanmedia.com/razatriad",
            "state": "North Carolina",
            "name": "La Raza Triad"
        },
        {
            "code": "KMRO",
            "url": "https://ice10.securenetsystems.net/KMRO",
            "state": "North Carolina",
            "name": "Radio Nueva Vida"
        },
        {
            "code": "WGOS",
            "url": "https://stream10.usastreams.com/8040/stream",
            "state": "North Carolina",
            "name": "Radio Vida Nueva"
        },
        {
            "code": "WGSP",
            "url": "https://stream-163.zeno.fm/xaz83f7uapjtv?zt=eyJhbGciOiJIUzI1NiJ9.eyJzdHJlYW0iOiJ4YXo4M2Y3dWFwanR2IiwiaG9zdCI6InN0cmVhbS0xNjMuemVuby5mbSIsInJ0dGwiOjUsImp0aSI6Ik10emkySllfU0F5bHlOZ0lqcTYtOFEiLCJpYXQiOjE3MzMzNjUzMTgsImV4cCI6MTczMzM2NTM3OH0.mL7rTxPUFj3-toPAXR4l7X1iOYMsRD47dImyMi8jFrU",
            "state": "North Carolina",
            "name": "Latina tu Musica"
        },
        {
            "code": "WYMY",
            "url": "https://18813.live.streamtheworld.com/WYMYPRIVATEAAC_SC?dist=triton-web&pname=StandardPlayerV4",
            "state": "North Carolina",
            "name": "La Ley"
        },
        {
            "code": "WSGH",
            "url": "https://ice7.securenetsystems.net/MOVIDITA",
            "state": "North Carolina",
            "name": "Activa"
        },
        {
            "code": "KVNR",
            "url": "https://stream-146.zeno.fm/2znsmu8d8zquv?zt=eyJhbGciOiJIUzI1NiJ9.eyJzdHJlYW0iOiIyem5zbXU4ZDh6cXV2IiwiaG9zdCI6InN0cmVhbS0xNDYuemVuby5mbSIsInJ0dGwiOjUsImp0aSI6IjZ5Q3RJRmN5UlVXaU9YaEVoTU9YcHciLCJpYXQiOjE3MzMzNzc0MTQsImV4cCI6MTczMzM3NzQ3NH0.E_1JOM9UODLnbrEjxdjAGDrVGqEZUbe1CwNI7zP7PRk",
            "state": "California",
            "name": "Little Saigon Radio"
        }
    ]
