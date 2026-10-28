package __BASE_PACKAGE__;

import com.claro.common.commonlogger.scan.EnableClaroCommonLoggerComponentScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.web.servlet.support.SpringBootServletInitializer;

@SpringBootApplication
@EnableClaroCommonLoggerComponentScan
public class __APPLICATION_CLASS__ extends SpringBootServletInitializer {

    public static void main(String[] args) {
        SpringApplication.run(__APPLICATION_CLASS__.class, args);
    }
}
