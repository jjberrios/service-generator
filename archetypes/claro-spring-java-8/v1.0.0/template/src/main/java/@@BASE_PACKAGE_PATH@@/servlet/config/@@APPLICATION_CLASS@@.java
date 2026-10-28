package @@BASE_PACKAGE@@.servlet.config;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.ComponentScan;

@SpringBootApplication
@ComponentScan({"@@BASE_PACKAGE@@"})
public class @@APPLICATION_CLASS@@ {

    public static void main(String[] args) {
        SpringApplication.run(@@APPLICATION_CLASS@@.class, args);
    }
}
