/*
 * HOST STUB: zephyr/logging/log.h
 *
 * Stand-in for -fsyntax-only checks. LOG_* expand to a variadic host
 * function so that format strings and argument expressions are still type
 * checked. LOG_MODULE_REGISTER is a no-op declaration.
 */
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#define LOG_LEVEL_NONE 0
#define LOG_LEVEL_ERR 1
#define LOG_LEVEL_WRN 2
#define LOG_LEVEL_INF 3
#define LOG_LEVEL_DBG 4

void pc_host_stub_log(const char *level, const char *fmt, ...)
	__attribute__((format(gnu_printf, 2, 3)));

#define LOG_ERR(fmt, ...) pc_host_stub_log("ERR", fmt, ##__VA_ARGS__)
#define LOG_WRN(fmt, ...) pc_host_stub_log("WRN", fmt, ##__VA_ARGS__)
#define LOG_INF(fmt, ...) pc_host_stub_log("INF", fmt, ##__VA_ARGS__)
#define LOG_DBG(fmt, ...) pc_host_stub_log("DBG", fmt, ##__VA_ARGS__)

#define LOG_MODULE_REGISTER(name, level) extern int pc_host_stub_log_module_##name
#define LOG_MODULE_DECLARE(name, level) extern int pc_host_stub_log_module_##name

#ifdef __cplusplus
}
#endif
