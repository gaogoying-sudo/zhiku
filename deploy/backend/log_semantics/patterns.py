from __future__ import annotations

import re

TIMESTAMP_RE = re.compile(
    r"^\[(?P<ts>(?:\d{4}[-_/]\d{2}[-_/]\d{2}|\d{2}-\d{2})[ _]\d{2}:\d{2}:\d{2})\]\s*"
)
TEMPERATURE_TRIPLET_RE = re.compile(
    r"(?P<filtered>-?\d+(?:\.\d+)?)_(?P<infrared>-?\d+(?:\.\d+)?)_(?P<output>-?\d+(?:\.\d+)?)\s*$"
)
COOKING_START_RE = re.compile(r"烹饪开始[:：]\s*(?P<name>.+?)_(?P<id>\d+)\s*-*")
VERSION_PATTERNS = {
    "jni_version": re.compile(r"JNI\s*版本[:：]\s*(?P<value>[\w.\-]+)", re.I),
    "firmware_version": re.compile(r"下位机版本[:：]\s*(?P<value>[\w.\-]+)", re.I),
    "app_version": re.compile(r"APP版本[:：]\s*(?P<value>[\w.\-]+)", re.I),
}
NETWORK_RE = re.compile(r"network request,\s*url:\s*(?P<url>\S+)", re.I)
SCENE_RE = re.compile(r"updateRobotScene:\s*scene\s*=\s*(?P<scene>[\w-]+)")
ACTIVITY_RE = re.compile(r"(?P<activity>[A-Za-z][A-Za-z0-9_]*Activity)\s+on(?P<action>Create|Destroy|Start|Stop|Resume|Pause)")
RECORDING_RE = re.compile(r"录制菜谱\s*[,，]\s*time\s*=\s*(?P<value>\d+)")
TEMP_LIMIT_RE = re.compile(r"设置温度上限[:：]\s*(?P<value>\d+)\s*(?P<result>成功|失败)?")
POWER_SET_RE = re.compile(r"功率设置为[:：]\s*(?P<power>\d+)\s*W", re.I)
POWER_RESULT_RE = re.compile(r"功率设置[_：:](?P<power>\d+)\s*W?[_：:]?(?P<result>成功|失败)", re.I)
POWER_FEEDBACK_RE = re.compile(
    r"功率[:：](?P<command>\d+)_(?P<actual>\d+),\s*母线[:：](?P<bus_voltage>-?[\d.]+)_(?P<bus_raw>-?[\d.]+),"
    r"\s*输出电流[:：](?P<current>-?[\d.]+),\s*频率[:：](?P<frequency>-?[\d.]+),"
    r"\s*温度[:：]_(?P<core>-?[\d.]+)_(?P<coil>-?[\d.]+)_(?P<output>-?[\d.]+)"
)
LEAN_START_RE = re.compile(r"开始倾锅操作[:：]\s*(?P<position>[\w-]+)")
LEAN_SUCCESS_RE = re.compile(r"倾锅操作[:：_](?P<position>[\w-]+).*?(?P<result>成功|失败)")
ROLL_START_RE = re.compile(r"开始转锅[:：]\s*(?P<mode>[\w-]+)")
ROLL_SUCCESS_RE = re.compile(r"转锅操作[_：:](?P<mode>[\w-]+).*?(?P<result>成功|失败)")
LIQUID_START_RE = re.compile(
    r"开始投液料[:：]\s*(?P<name>.+?)_(?P<id>\d+)_(?P<amount>[\d.]+)_GRAM_(?P<runtime>\d+)_RUNTIME"
)
LIQUID_SUCCESS_RE = re.compile(r"投液料_(?P<name>.+?)_(?P<amount>[\d.]+)_GRAM_(?P<runtime>\d+)_(?P<result>成功|失败)")
LIQUID_CONSUMED_RE = re.compile(r"消耗液料(?P<name>[^,，]+)[,，]\s*(?P<amount>[\d.]+)g")
LIQUID_CAPACITY_RE = re.compile(r"设置液料当前容量(?P<name>[^,，]+)[,，]\s*(?P<remaining>[\d.]+)g")
WEIGH_START_RE = re.compile(r"开始称重[:：]\s*(?P<channel>.+?)_READ_(?P<target>[\d.]+)")
WEIGH_SUCCESS_RE = re.compile(r"称重_(?P<channel>.+?)_(?P<target>[\d.]+)_GRAM_(?P<result>成功|失败)")
WEIGH_RESULT_RE = re.compile(
    r"onWeightResult:\s*(?P<channel>\S+)\s+weight:\s*(?P<raw>-?\d+).*?getValue\(\):\s*(?P<target>[\d.]+)\s+originWeight:\s*(?P<origin>-?\d+)"
)
SPEECH_START_RE = re.compile(r"CNEngine speak\s*=\s*(?P<text>.*?),code\s*=\s*(?P<code>-?\d+)")
SPEECH_COMPLETE_RE = re.compile(r"onSpeechComplete text\s*=\s*(?P<text>.*)")
DATA_COLLECT_RE = re.compile(r"DataCollectManager:\s*(?P<payload>.*)")
WORK_HALL_RE = re.compile(r"workTime:\s*(?P<work>\d+).*?hall:\s*(?P<hall>-?\d+)")
COMMAND_PATTERNS = {
    "command_send": re.compile(r"\bsendMsg\b|send to mcu", re.I),
    "command_read": re.compile(r"\breadResult\b|\bread line\b", re.I),
    "command_result": re.compile(r"\bfindResult\b", re.I),
}
ERROR_RE = re.compile(r"no FrameID|timeout|fail|error|heaterGetErrCode|Exception|crash", re.I)
UNKNOWN_KEYWORDS_RE = re.compile(r"功率|温度|投料|液料|倾锅|转锅|称重|error|fail|FrameID", re.I)
