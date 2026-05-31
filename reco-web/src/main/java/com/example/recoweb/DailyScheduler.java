package com.example.recoweb;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class DailyScheduler {
    private static final Logger log = LoggerFactory.getLogger(DailyScheduler.class);

    private final TradingRunnerService runnerService;

    public DailyScheduler(TradingRunnerService runnerService) {
        this.runnerService = runnerService;
    }

    @Scheduled(cron = "${trading.schedule-cron}", zone = "${trading.schedule-zone}")
    public void runDaily() {
        TradingRunnerService.RunResult result = runnerService.runNow("scheduled");
        if (result.success()) {
            log.info("Scheduled run succeeded. exitCode={}", result.exitCode());
            return;
        }
        log.error("Scheduled run failed. exitCode={} output={}", result.exitCode(), result.output());
    }
}
