package com.example.recoweb;

import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

@Service
public class TradingRunnerService {
    private final TradingProperties properties;

    public TradingRunnerService(TradingProperties properties) {
        this.properties = properties;
    }

    public RunResult runNow(String trigger) {
        ProcessBuilder builder = new ProcessBuilder("bash", "-lc", properties.getRunCommand());
        builder.redirectErrorStream(true);

        try {
            Process process = builder.start();
            String output;
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                StringBuilder sb = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    if (!sb.isEmpty()) {
                        sb.append("\n");
                    }
                    sb.append(line);
                }
                output = sb.toString();
            }

            int exitCode = process.waitFor();
            return new RunResult(trigger, exitCode == 0, exitCode, output);
        } catch (IOException | InterruptedException ex) {
            Thread.currentThread().interrupt();
            return new RunResult(trigger, false, -1, ex.getMessage());
        }
    }

    public record RunResult(String trigger, boolean success, int exitCode, String output) {
    }
}
