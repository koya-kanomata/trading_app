package com.example.recoweb;

import jakarta.validation.constraints.NotBlank;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties(prefix = "trading")
public class TradingProperties {
    @NotBlank
    private String baseDir;

    @NotBlank
    private String runCommand;

    @NotBlank
    private String ordersCsv;

    @NotBlank
    private String reportMd;

    @NotBlank
    private String auditLogCsv;

    @NotBlank
    private String scheduleCron;

    @NotBlank
    private String scheduleZone;

    public String getBaseDir() {
        return baseDir;
    }

    public void setBaseDir(String baseDir) {
        this.baseDir = baseDir;
    }

    public String getRunCommand() {
        return runCommand;
    }

    public void setRunCommand(String runCommand) {
        this.runCommand = runCommand;
    }

    public String getOrdersCsv() {
        return ordersCsv;
    }

    public void setOrdersCsv(String ordersCsv) {
        this.ordersCsv = ordersCsv;
    }

    public String getReportMd() {
        return reportMd;
    }

    public void setReportMd(String reportMd) {
        this.reportMd = reportMd;
    }

    public String getAuditLogCsv() {
        return auditLogCsv;
    }

    public void setAuditLogCsv(String auditLogCsv) {
        this.auditLogCsv = auditLogCsv;
    }

    public String getScheduleCron() {
        return scheduleCron;
    }

    public void setScheduleCron(String scheduleCron) {
        this.scheduleCron = scheduleCron;
    }

    public String getScheduleZone() {
        return scheduleZone;
    }

    public void setScheduleZone(String scheduleZone) {
        this.scheduleZone = scheduleZone;
    }
}
