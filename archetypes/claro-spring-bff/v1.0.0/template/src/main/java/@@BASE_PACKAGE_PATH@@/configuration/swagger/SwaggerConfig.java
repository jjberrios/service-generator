package @@BASE_PACKAGE@@.configuration.swagger;


import io.swagger.v3.oas.annotations.OpenAPIDefinition;
import io.swagger.v3.oas.annotations.servers.Server;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.info.License;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@OpenAPIDefinition(servers = {@Server(url = "/")})
@Configuration
public class SwaggerConfig {

    @Bean
    public OpenAPI springShopOpenAPI() {
        return new OpenAPI()
                .info(new Info().title("@@ARTIFACT_ID@@")
                        .description("API Documentation")
                        .version("1.0.0")
                        .contact(new Contact().name("Claro").email("claro@claro.com.pe"))
                        .license(new License().name("Apache 2.0").url("http://springdoc.org")));
    }
}