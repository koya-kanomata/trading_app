package com.example.recoweb;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class RecoWebApplication {
    public static void main(String[] args) {
        SpringApplication.run(RecoWebApplication.class, args);
    }
}
