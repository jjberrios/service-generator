package @@BASE_PACKAGE@@.servlet.config;

import java.io.File;
import java.util.Properties;

import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.web.servlet.support.SpringBootServletInitializer;

public class ServletInitializer extends SpringBootServletInitializer {

    @Override
    protected SpringApplicationBuilder configure(SpringApplicationBuilder application) {
        return application.sources(@@APPLICATION_CLASS@@.class).properties(getProperties());
    }

    static Properties getProperties() {
        Properties props = new Properties();
        String configPath = System.getProperty("@@CONFIG_ROOT_PROPERTY@@") + "@@CONFIG_SUBDIRECTORY@@" + File.separator
                + "application.properties";
        props.put("spring.config.location", "file:" + configPath);
        return props;
    }
}
