package @@BASE_PACKAGE@@.configuration.security;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
@EnableWebSecurity
public class SecurityConfig {

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
                // CSRF está deshabilitado porque esta es una API REST stateless que usa JWT
                // Los tokens JWT en headers no son vulnerables a CSRF
                // Esta API no usa cookies de sesión, por lo que CSRF no es aplicable
                .csrf(csrf -> csrf.disable()) // NOSONAR - API REST stateless con autenticación JWT
                .authorizeHttpRequests(auth -> auth
                        // Permitir acceso público a todos los endpoints
                        .anyRequest().permitAll())
                .formLogin(form -> form.disable())
                .httpBasic(basic -> basic.disable());
                

        return http.build();
    }
}
